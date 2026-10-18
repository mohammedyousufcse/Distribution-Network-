import inspect
import time
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from app.connectors.registry import get_available_connectors, get_connector
from app.logging import get_logger
from app.models.errors import ConnectorException, IdempotencyConflictError
from app.models.payloads import ContentPayload
from app.models.policy import ERROR_CODE_FREQUENCY_CAP, ERROR_CODE_SPEC_VIOLATION
from app.services.catalogue_service import catalogue_service
from app.services.certification_service import certification_harness
from app.services.idempotency_service import get_idempotency_service
from app.services.job_service import JobRecord, JobStatus, get_job_service
from app.services.policy_service import get_policy_service

logger = get_logger("app.api.connector")

router = APIRouter(prefix="/connector/v1", tags=["Connectors"])

SUPPORTED_METHODS = {
    "validate",
    "publish",
    "get_status",
    "delete",
    "fetch_metrics",
    "refresh_auth",
    "build_assist_pack",
    "manifest",
}


class JobStatusResponse(BaseModel):
    """Schema for background job status output."""

    job_id: str = Field(description="Unique background job identifier.")
    status: str = Field(description="Current status: queued, running, succeeded, or failed.")
    connector_key: str = Field(description="Target destination connector.")
    created_at: str = Field(description="Job creation timestamp in ISO-8601 UTC.")
    updated_at: str = Field(description="Last update timestamp in ISO-8601 UTC.")
    duration_ms: Optional[float] = Field(default=None, description="Execution duration in milliseconds.")
    result: Optional[Dict[str, Any]] = Field(default=None, description="Published post details on success.")
    error: Optional[Dict[str, Any]] = Field(default=None, description="Structured error payload on failure.")


class JobAcceptedResponse(BaseModel):
    """Schema returned when an operation is accepted for background execution (HTTP 202)."""

    job_id: str = Field(description="Unique background job identifier.")
    status: str = Field(description="Initial status, usually 'queued'.")
    connector_key: str = Field(description="Target destination connector.")
    message: str = Field(description="Informational acceptance message.")
    status_url: str = Field(description="URL to query job execution status.")
    created_at: str = Field(description="Job creation timestamp in ISO-8601 UTC.")


class ConnectorRequest(BaseModel):
    """Unified request body supporting both standard and Appendix A connector contracts."""

    content: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Content payload for 'validate' and 'publish'. Must contain a non-empty 'text' string.",
        examples=[{"text": "Sample announcement to publish to mock destination"}],
    )
    rendition: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Appendix A rendition object (alias for content).",
    )
    destination: Optional[Any] = Field(
        default=None,
        description="Target destination configuration dict or stable destination ID.",
    )
    connection: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Connection credentials dict or authentication tokens.",
    )
    post_id: Optional[str] = Field(
        default=None,
        description="Unique post identifier required for 'get_status' and 'delete'.",
        examples=["mock_a1b2c3d4e5f6"],
    )
    platform_post_id: Optional[str] = Field(
        default=None,
        description="Appendix A platform post ID (alias for post_id).",
    )
    async_mode: Optional[bool] = Field(
        default=None,
        alias="async",
        description="Optional flag to request asynchronous background processing.",
    )
    idempotency_key: Optional[str] = Field(
        default=None,
        description="Optional idempotency key in request body.",
    )
    since: Optional[str] = Field(
        default=None,
        description="ISO-8601 timestamp filter for 'fetch_metrics'.",
    )

    model_config = {
        "extra": "allow",
        "populate_by_name": True,
    }

    def get_effective_content(self) -> Optional[Dict[str, Any]]:
        """Extract content from explicit 'rendition', 'content', or top-level payload."""
        if self.rendition is not None:
            return self.rendition
        if self.content is not None:
            return self.content
        extra = self.model_extra or {}
        if extra:
            filtered = {
                k: v
                for k, v in extra.items()
                if k not in {"async", "mode", "destination", "connection", "post_id", "platform_post_id"}
            }
            return filtered if filtered else None
        return None

    def get_effective_post_id(self) -> Optional[str]:
        """Extract post identifier from platform_post_id, post_id, or extra fields."""
        if self.platform_post_id:
            return self.platform_post_id
        if self.post_id:
            return self.post_id
        extra = self.model_extra or {}
        return extra.get("platform_post_id") or extra.get("post_id") or extra.get("id")


async def _invoke_connector(connector: Any, method_name: str, **kwargs: Any) -> Any:
    """Safely invoke connector method adapting between legacy and Appendix A signatures."""
    method = getattr(connector, method_name, None)
    if method is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Method '{method_name}' is not supported by connector '{connector.name}'.",
        )

    sig = inspect.signature(method)
    param_objs = list(sig.parameters.values())
    has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in param_objs)
    non_var_params = [
        p.name for p in param_objs
        if p.kind not in (inspect.Parameter.VAR_KEYWORD, inspect.Parameter.VAR_POSITIONAL)
    ]

    dest = kwargs.get("destination") or {}
    conn = kwargs.get("connection") or {}
    raw_content = kwargs.get("content") or kwargs.get("rendition") or {}
    idem_key = kwargs.get("idempotency_key")
    pid = kwargs.get("platform_post_id") or kwargs.get("post_id")

    payload_obj = raw_content
    if isinstance(raw_content, dict):
        extra_meta = dict(raw_content.get("metadata", {})) if isinstance(raw_content.get("metadata"), dict) else {}
        if "simulation" in raw_content:
            extra_meta["simulation"] = raw_content["simulation"]
        if "tags" in raw_content:
            extra_meta["tags"] = raw_content["tags"]
        payload_obj = ContentPayload(
            title=raw_content.get("title"),
            text=raw_content.get("text", ""),
            media_urls=raw_content.get("media_urls"),
            metadata=extra_meta,
            **{k: v for k, v in raw_content.items() if k not in ("title", "text", "media_urls", "metadata")},
        )
        if raw_content.get("simulation"):
            if isinstance(dest, dict):
                dest["simulation"] = True
            if isinstance(conn, dict):
                conn["simulation"] = True

    call_args = []
    call_kwargs = {}

    if method_name in ("validate", "publish"):
        if len(non_var_params) <= 1:
            # Single positional: validate(content) / publish(content, **kwargs)
            target = raw_content if isinstance(raw_content, dict) else payload_obj
            call_args.append(target)
            if has_var_kw:
                call_kwargs["destination"] = dest
                call_kwargs["connection"] = conn
                if idem_key:
                    call_kwargs["idempotency_key"] = idem_key
        else:
            # Multi-param: publish(payload, destination, connection, idempotency_key)
            first_arg = payload_obj if any(k in non_var_params[0] for k in ("payload", "rendition", "content")) else raw_content
            call_args.append(first_arg)
            if len(non_var_params) > 1:
                call_args.append(dest)
            if len(non_var_params) > 2:
                call_args.append(conn)
            if len(non_var_params) > 3 or has_var_kw:
                call_kwargs["idempotency_key"] = idem_key
    elif method_name in ("get_status", "delete", "fetch_metrics"):
        call_args.append(str(pid))
        if len(non_var_params) <= 1:
            if has_var_kw:
                call_kwargs["destination"] = dest
                call_kwargs["connection"] = conn
                if method_name == "fetch_metrics" and kwargs.get("since"):
                    call_kwargs["since"] = kwargs.get("since")
        else:
            if len(non_var_params) > 1:
                call_args.append(dest)
            if len(non_var_params) > 2:
                call_args.append(conn)
            if (len(non_var_params) > 3 or has_var_kw) and method_name == "fetch_metrics":
                call_kwargs["since"] = kwargs.get("since")
    elif method_name == "build_assist_pack":
        call_args.append(payload_obj)
        if len(non_var_params) > 1:
            call_args.append(dest)
    elif method_name == "refresh_auth":
        call_args.append(conn)

    if inspect.iscoroutinefunction(method):
        return await method(*call_args, **call_kwargs)
    else:
        return method(*call_args, **call_kwargs)


async def process_background_publish(
    job_id: str,
    connector_key: str,
    content: Dict[str, Any],
    destination: Optional[Dict[str, Any]] = None,
    connection: Optional[Dict[str, Any]] = None,
    delay: float = 0.0,
) -> None:
    """Execute publish in the background, updating JobRecord status and results."""
    import asyncio
    job_svc = get_job_service()
    job_svc.update_status(job_id, status=JobStatus.RUNNING)
    logger.info(
        f"Background job '{job_id}' started execution",
        extra={
            "event": "job_started",
            "job_id": job_id,
            "connector_key": connector_key,
        },
    )

    t0 = time.perf_counter()
    if delay > 0:
        await asyncio.sleep(delay)

    connector = get_connector(connector_key)
    if connector is None:
        duration_ms = round((time.perf_counter() - t0) * 1000, 2)
        err = {
            "error_code": "CONNECTOR_NOT_FOUND",
            "message": f"Connector '{connector_key}' not found.",
            "detail": f"Connector '{connector_key}' not found.",
        }
        job_svc.update_status(job_id, status=JobStatus.FAILED, error=err, duration_ms=duration_ms)
        logger.error(
            f"Background job '{job_id}' failed: connector not found",
            extra={
                "event": "job_failed",
                "job_id": job_id,
                "connector_key": connector_key,
                "duration_ms": duration_ms,
                "error_code": "CONNECTOR_NOT_FOUND",
            },
        )
        return

    try:
        raw_result = await _invoke_connector(
            connector,
            "publish",
            content=content,
            destination=destination or {},
            connection=connection or {},
        )
        if hasattr(raw_result, "model_dump"):
            result = raw_result.model_dump()
        elif isinstance(raw_result, dict):
            result = dict(raw_result)
        else:
            result = {"success": True, "id": str(raw_result)}

        pid = str(result.get("platform_post_id") or result.get("id") or "post_1")
        result["platform_post_id"] = pid
        result["id"] = pid
        result["success"] = result.get("success", True)

        duration_ms = round((time.perf_counter() - t0) * 1000, 2)
        if result.get("success"):
            job_svc.update_status(
                job_id, status=JobStatus.SUCCEEDED, result=result, duration_ms=duration_ms
            )
            logger.info(
                f"Background job '{job_id}' completed successfully",
                extra={
                    "event": "job_succeeded",
                    "job_id": job_id,
                    "connector_key": connector_key,
                    "duration_ms": duration_ms,
                    "post_id": pid,
                },
            )
        else:
            err = {
                "error_code": ERROR_CODE_SPEC_VIOLATION,
                "message": result.get("error", "Failed to publish content."),
                "detail": result.get("error", "Failed to publish content."),
            }
            job_svc.update_status(job_id, status=JobStatus.FAILED, error=err, duration_ms=duration_ms)
            logger.error(
                f"Background job '{job_id}' failed",
                extra={
                    "event": "job_failed",
                    "job_id": job_id,
                    "connector_key": connector_key,
                    "duration_ms": duration_ms,
                    "error_code": ERROR_CODE_SPEC_VIOLATION,
                },
            )
    except ConnectorException as exc:
        duration_ms = round((time.perf_counter() - t0) * 1000, 2)
        err = exc.to_dict()
        job_svc.update_status(job_id, status=JobStatus.FAILED, error=err, duration_ms=duration_ms)
        logger.error(
            f"Background job '{job_id}' failed with ConnectorException: {exc.error_code}",
            extra={
                "event": "job_failed",
                "job_id": job_id,
                "connector_key": connector_key,
                "duration_ms": duration_ms,
                "error_code": exc.error_code,
            },
        )
    except Exception as exc:
        duration_ms = round((time.perf_counter() - t0) * 1000, 2)
        err = {
            "error_code": "INTERNAL_ERROR",
            "message": str(exc),
            "detail": str(exc),
        }
        job_svc.update_status(job_id, status=JobStatus.FAILED, error=err, duration_ms=duration_ms)
        logger.error(
            f"Background job '{job_id}' failed with unexpected exception",
            exc_info=True,
            extra={
                "event": "job_failed",
                "job_id": job_id,
                "connector_key": connector_key,
                "duration_ms": duration_ms,
                "error_code": "INTERNAL_ERROR",
            },
        )


@router.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
    summary="Get background job status",
    description=(
        "Retrieve the execution status and results of an asynchronous connector operation.\n\n"
        "**Status States:**\n"
        "- `queued`: Accepted and awaiting execution.\n"
        "- `running`: In progress.\n"
        "- `succeeded`: Completed with published post details in `result`.\n"
        "- `failed`: Failed with error details in `error`.\n\n"
        "*Note: Job status records are stored in memory and reset upon application restart.*"
    ),
    responses={
        200: {
            "description": "Job status retrieved successfully.",
        },
        404: {
            "description": "Not Found - Job identifier not found.",
        },
    },
)
def get_job_status(job_id: str) -> Any:
    """Retrieve current background job details by job ID."""
    job = get_job_service().get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found.",
        )
    return job.to_dict()


@router.get(
    "/destinations",
    summary="List destination catalogue",
    description="List all configuration-driven destinations registered in destinations.yaml.",
)
def list_destinations(connector_key: Optional[str] = Query(default=None)) -> Any:
    """Retrieve all configured destination profiles."""
    return catalogue_service.list_destinations(connector_key=connector_key)


@router.get(
    "/destinations/{destination_id}",
    summary="Get destination profile",
    description="Retrieve destination details, rate limits, format limits, and posting rules.",
)
def get_destination(destination_id: str) -> Any:
    """Retrieve single destination profile by stable ID."""
    dest = catalogue_service.get_destination(destination_id)
    if not dest:
        raise HTTPException(status_code=404, detail=f"Destination '{destination_id}' not found.")
    return dest


@router.post(
    "/destinations/{destination_id}/certify",
    summary="Run destination certification probe",
    description="Executes automated validation, test publish, status check, and cleanup deletion.",
)
async def certify_destination(
    destination_id: str,
    simulation: bool = Query(default=False, description="Run probe in credential-free simulation mode"),
) -> Any:
    """Run full automated destination certification probe."""
    return await certification_harness.certify_destination(destination_id, simulation=simulation)


@router.post(
    "/tailor",
    summary="Tailor content for destination",
    description="Adapts content for destination surface (discussion prompts for forums, canonical links for articles, word-boundary truncation).",
)
def tailor_content_endpoint(payload: Dict[str, Any]) -> Any:
    """Tailor title, body text, tags, and formatting to a target destination."""
    from app.services.tailoring_service import tailoring_service
    content = payload.get("content") or payload.get("rendition") or payload
    dest = payload.get("destination") or {}
    if isinstance(dest, str):
        dest_obj = catalogue_service.get_destination(dest)
        if dest_obj:
            dest = dest_obj
        else:
            dest = {"id": dest, "connector_key": dest}
    return tailoring_service.tailor_content(content, dest)


@router.post(
    "/score_relevance",
    summary="Score destination audience relevance",
    description="Scores destination affinity from 1 to 5 against IncuBrix core audiences (AI, video, marketing, SaaS, creators, founders).",
)
def score_relevance_endpoint(payload: Dict[str, Any]) -> Any:
    """Score destination alignment against IncuBrix audience segments (1-5)."""
    from app.services.tailoring_service import tailoring_service
    dest = payload.get("destination") or payload
    if isinstance(dest, str):
        dest_obj = catalogue_service.get_destination(dest)
        if dest_obj:
            dest = dest_obj
        else:
            dest = {"id": dest, "name": dest}
    return tailoring_service.score_relevance(dest)


@router.post(
    "/catalogue/import",
    summary="Import destination catalogue from CSV",
    description="Validates, de-duplicates, checks reachability, and imports destinations from CSV in under 5 minutes.",
)
async def import_catalogue_endpoint(payload: Dict[str, Any]) -> Any:
    """Import and validate destinations from CSV with row-by-row reporting."""
    from pathlib import Path
    from app.services.catalogue_import_service import catalogue_import_service
    csv_text = payload.get("csv_content") or payload.get("csv") or ""
    filename = payload.get("filename", "upload.csv")
    mock_mode = payload.get("mock_reachability", True)

    csv_path = payload.get("csv_path") or payload.get("file_path") or payload.get("path")
    if csv_path and not csv_text:
        p = Path(str(csv_path))
        if p.exists():
            csv_text = p.read_text(encoding="utf-8", errors="replace")
            filename = p.name
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"CSV file at path '{csv_path}' was not found.",
            )

    return await catalogue_import_service.import_csv_content(csv_text, filename=filename, mock_reachability=mock_mode)


@router.post(
    "/rules/propose",
    summary="Propose posting rules from community guidelines",
    description="Analyzes guidelines text to propose posting rules (weekly cap, self-promotion, links, AI disclosure).",
)
def propose_rules_endpoint(payload: Dict[str, Any]) -> Any:
    """Analyze community text and generate proposed rules awaiting human confirmation."""
    from app.services.rules_capture_service import RulesCaptureService
    community_name = payload.get("community_name") or payload.get("name") or "Community"
    rules_text = payload.get("rules_text") or payload.get("text") or payload.get("guidelines") or ""
    rules_url = payload.get("rules_url") or payload.get("url")
    return RulesCaptureService.propose_rules(community_name=community_name, rules_text=rules_text, rules_url=rules_url)


@router.post(
    "/rules/confirm",
    summary="Confirm proposed posting rules",
    description="Human review step that confirms or overrides proposed posting rules before activation.",
)
def confirm_rules_endpoint(payload: Dict[str, Any]) -> Any:
    """Confirm a proposed rule set with optional overrides."""
    from app.services.rules_capture_service import RulesCaptureService
    proposal_id = payload.get("proposal_id")
    if not proposal_id:
        raise HTTPException(status_code=400, detail="proposal_id is required.")
    confirmed_by = payload.get("confirmed_by", "community_manager")
    overrides = payload.get("overrides")
    try:
        return RulesCaptureService.confirm_rules(proposal_id=proposal_id, confirmed_by=confirmed_by, overrides=overrides)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post(
    "/recommend",
    summary="Recommend and rank destinations for content",
    description="Ranks destinations in catalogue by audience relevance, format affinity, and rule compatibility with explanations.",
)
def recommend_destinations_endpoint(payload: Dict[str, Any]) -> Any:
    """Recommend best fit destinations for content item."""
    from app.services.recommender_service import RecommenderService
    text = payload.get("text") or ""
    title = payload.get("title")
    tags = payload.get("tags") or []
    pillar = payload.get("audience_pillar") or payload.get("pillar")
    is_promo = bool(payload.get("is_promotional", False))
    is_ai = bool(payload.get("is_ai_generated", False))
    limit = int(payload.get("limit", 10))
    return RecommenderService.recommend_destinations(
        text=text,
        title=title,
        tags=tags,
        audience_pillar=pillar,
        is_promotional=is_promo,
        is_ai_generated=is_ai,
        limit=limit,
    )


@router.get(
    "/recommend/benchmark",
    summary="Benchmark recommender precision@k",
    description="Evaluates ranking precision of top 10 recommendations across labelled ground-truth dataset.",
)
def benchmark_recommendations_endpoint(k: int = 10) -> Any:
    """Run precision benchmark on ground truth labelled dataset."""
    from app.services.recommender_service import RecommenderService
    return RecommenderService.evaluate_precision_at_k(k=k)



@router.get(
    "/{connector_key}/manifest",
    summary="Get connector manifest",
    description="Retrieve connector metadata, supported content types, rate limits, capabilities, and error mappings.",
)
def get_connector_manifest(connector_key: str) -> Any:
    """Retrieve connector specification manifest."""
    connector = get_connector(connector_key)
    if not connector:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connector '{connector_key}' not found. Available: {get_available_connectors()}",
        )
    return connector.get_manifest()


@router.post(
    "/{connector_key}/{method}",
    summary="Execute connector action",
    description=(
        "Dispatches an operation to a registered destination connector with policy enforcement.\n\n"
        "**Supported Methods:**\n"
        "- `validate`: Validates content structure and destination constraints (length, non-empty text).\n"
        "- `publish`: Enforces destination policy, frequency cap, and idempotency before simulating publishing locally.\n"
        "- `get_status`: Looks up post details by ID (requires `post_id` in request body).\n"
        "- `delete`: Deletes a post by ID (requires `post_id` in request body).\n"
        "- `fetch_metrics`: Fetches normalized engagement metrics.\n"
        "- `refresh_auth`: Refreshes authorization token when supported.\n"
        "- `build_assist_pack`: Generates operator pack for assisted destinations.\n"
        "- `manifest`: Returns connector capability manifest.\n\n"
        "**Idempotency (`Idempotency-Key` header):**\n"
        "- For `publish`, pass the optional `Idempotency-Key: <unique_string>` header.\n"
        "- **First Request:** Processes publication normally and stores the response against `(connector_key, key)`.\n"
        "- **Duplicate Request:** When the same key is submitted again with the same request payload within the TTL window, "
        "the original response and original post ID are returned without creating another post or consuming frequency quota.\n"
        "- **Payload Conflict:** If the same key is reused with a different request payload, the server returns "
        "HTTP 409 Conflict with `error_code: IDEMPOTENCY_CONFLICT`.\n"
        "- **Scope & TTL:** Keys are strictly scoped per connector and expire automatically after `IDEMPOTENCY_TTL_SECONDS` (default 300s).\n"
        "- **Concurrency Safety:** Concurrent duplicate requests within the process are synchronized so only one post is created.\n\n"
        "*Important: Idempotency records are maintained entirely in-memory within this single application process; "
        "state resets when the process/container restarts and does not synchronize across multi-replica deployments.*"
    ),
    responses={
        200: {
            "description": "Operation completed successfully.",
        },
        202: {
            "description": "Accepted - Publish operation accepted for background processing.",
        },
        400: {
            "description": "Bad Request - Invalid method, spec violation, missing content, or missing post ID.",
        },
        404: {
            "description": "Not Found - Unknown connector key or post ID not found.",
        },
        409: {
            "description": "Conflict - Idempotency key reused with a different request payload.",
        },
        429: {
            "description": "Too Many Requests - Frequency cap exceeded.",
        },
    },
)
async def handle_connector_action(
    connector_key: str,
    method: str,
    background_tasks: BackgroundTasks,
    request: Optional[ConnectorRequest] = None,
    async_mode: Optional[bool] = Query(
        default=None,
        alias="async",
        description="Trigger asynchronous background execution for publish operations.",
    ),
    prefer: Optional[str] = Header(
        default=None,
        alias="Prefer",
        description="Standard RFC 7240 header; set to 'respond-async' for background processing.",
    ),
    idempotency_key: Optional[str] = Header(
        default=None,
        alias="Idempotency-Key",
        description="Optional idempotency key for 'publish' operations to prevent duplicate posts.",
        examples=["idem_123e4567-e89b-12d3-a456-426614174000"],
    ),
) -> Any:
    """Dispatch connector operation based on connector key and method."""
    start_time = time.perf_counter()

    def get_duration_ms() -> float:
        return round((time.perf_counter() - start_time) * 1000, 2)

    logger.info(
        "Connector operation started",
        extra={
            "event": "operation_start",
            "connector_key": connector_key,
            "method": method,
            "operation": method,
            "idempotency_key": idempotency_key,
        },
    )

    # 1. Resolve connector implementation
    connector = get_connector(connector_key)
    if connector is None:
        duration_ms = get_duration_ms()
        logger.warning(
            f"Connector '{connector_key}' not found",
            extra={
                "event": "connector_not_found",
                "connector_key": connector_key,
                "method": method,
                "operation": method,
                "duration_ms": duration_ms,
                "status_code": status.HTTP_404_NOT_FOUND,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Connector '{connector_key}' not found. "
                f"Available connectors: {get_available_connectors()}."
            ),
        )

    # 2. Validate requested method
    norm_method = method.strip().lower()
    if norm_method not in SUPPORTED_METHODS:
        duration_ms = get_duration_ms()
        logger.warning(
            f"Unsupported method '{method}' requested",
            extra={
                "event": "unsupported_method",
                "connector_key": connector_key,
                "method": method,
                "operation": method,
                "duration_ms": duration_ms,
                "status_code": status.HTTP_400_BAD_REQUEST,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported method '{method}'. "
                f"Supported methods: {sorted(list(SUPPORTED_METHODS))}."
            ),
        )

    req = request or ConnectorRequest()
    policy_svc = get_policy_service()

    # Resolve destination and connection
    dest_obj = req.destination
    if isinstance(dest_obj, str):
        dest_config = catalogue_service.get_destination(dest_obj) or {
            "id": dest_obj,
            "connector_key": connector_key,
        }
    elif isinstance(dest_obj, dict):
        dest_config = dest_obj
    else:
        matching = catalogue_service.list_destinations(connector_key)
        dest_config = matching[0] if matching else {"id": connector_key, "connector_key": connector_key}

    conn_obj = req.connection
    if conn_obj is None and isinstance(dest_config, dict) and "id" in dest_config:
        conn_obj = catalogue_service.resolve_connection(dest_config["id"])
    if conn_obj is None:
        conn_obj = {}

    # Propagate simulation flag across dest_config and conn_obj if specified anywhere
    eff_content = req.get_effective_content()
    is_sim_mode = (
        (isinstance(eff_content, dict) and bool(eff_content.get("simulation")))
        or (isinstance(dest_config, dict) and bool(dest_config.get("simulation")))
        or (isinstance(conn_obj, dict) and bool(conn_obj.get("simulation")))
    )
    if is_sim_mode:
        if isinstance(dest_config, dict):
            dest_config["simulation"] = True
        if isinstance(conn_obj, dict):
            conn_obj["simulation"] = True

    # Method: manifest
    if norm_method == "manifest":
        return connector.get_manifest()

    # Method: refresh_auth
    if norm_method == "refresh_auth":
        return await _invoke_connector(connector, "refresh_auth", connection=conn_obj)

    # Method: build_assist_pack
    if norm_method == "build_assist_pack":
        content = req.get_effective_content() or {}
        return await _invoke_connector(
            connector,
            "build_assist_pack",
            content=content,
            destination=dest_config,
        )

    # Method: fetch_metrics
    if norm_method == "fetch_metrics":
        post_id = req.get_effective_post_id()
        if not post_id or not str(post_id).strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Field 'post_id' or 'platform_post_id' is required for method 'fetch_metrics'.",
            )
        return await _invoke_connector(
            connector,
            "fetch_metrics",
            platform_post_id=str(post_id).strip(),
            destination=dest_config,
            connection=conn_obj,
            since=req.since,
        )

    # 3. Handle 'validate'
    if norm_method == "validate":
        content = req.get_effective_content()
        target_content = content if content is not None else {}
        # First evaluate against destination policy (e.g. length, non-empty text)
        policy_check = policy_svc.validate_content(connector_key, target_content)
        if not policy_check["valid"]:
            duration_ms = get_duration_ms()
            err_code = policy_check.get("error_code", ERROR_CODE_SPEC_VIOLATION)
            logger.warning(
                "Destination policy validation failed",
                extra={
                    "event": "policy_validation_failure",
                    "connector_key": connector_key,
                    "method": "validate",
                    "operation": "validate",
                    "error_code": err_code,
                    "duration_ms": duration_ms,
                    "status_code": status.HTTP_200_OK,
                },
            )
            return policy_check

        # Then evaluate connector-level validation
        raw_result = await _invoke_connector(
            connector,
            "validate",
            content=target_content,
            destination=dest_config,
            connection=conn_obj,
        )
        if hasattr(raw_result, "model_dump"):
            result = raw_result.model_dump()
        elif isinstance(raw_result, dict):
            result = dict(raw_result)
        else:
            result = {"valid": True, "ok": True}

        ok = bool(result.get("ok", result.get("valid", True)))
        violations = result.get("violations", result.get("errors", []))
        result["ok"] = ok
        result["valid"] = ok
        result["violations"] = violations
        result["errors"] = violations

        duration_ms = get_duration_ms()
        if not result.get("valid"):
            logger.warning(
                "Connector validation rejected content",
                extra={
                    "event": "policy_validation_failure",
                    "connector_key": connector_key,
                    "method": "validate",
                    "operation": "validate",
                    "error_code": ERROR_CODE_SPEC_VIOLATION,
                    "duration_ms": duration_ms,
                    "status_code": status.HTTP_200_OK,
                },
            )
        else:
            logger.info(
                "Connector operation completed successfully",
                extra={
                    "event": "operation_success",
                    "connector_key": connector_key,
                    "method": "validate",
                    "operation": "validate",
                    "duration_ms": duration_ms,
                    "status_code": status.HTTP_200_OK,
                },
            )
        return result

    # 4. Handle 'publish'
    if norm_method == "publish":
        content = req.get_effective_content()
        if content is None:
            duration_ms = get_duration_ms()
            logger.warning(
                "Missing required 'content' field for publish",
                extra={
                    "event": "missing_content",
                    "connector_key": connector_key,
                    "method": "publish",
                    "operation": "publish",
                    "duration_ms": duration_ms,
                    "status_code": status.HTTP_400_BAD_REQUEST,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Field 'content' is required for method 'publish'.",
            )

        # Check delay specified in content or request
        delay_val = 0.0
        for k in ("simulate_delay", "delay_seconds", "delay"):
            if isinstance(content, dict) and k in content and isinstance(content[k], (int, float)):
                delay_val = float(content[k])
                break

        is_async = False
        if async_mode is True or req.async_mode is True:
            is_async = True
        elif prefer and "respond-async" in prefer.lower():
            is_async = True
        elif delay_val >= 2.0 and async_mode is not False and req.async_mode is not False:
            is_async = True

        effective_idem = req.idempotency_key or idempotency_key
        clean_idem_key = (
            effective_idem.strip()
            if effective_idem and effective_idem.strip()
            else None
        )

        if clean_idem_key:
            idem_svc = get_idempotency_service()
            payload_hash = idem_svc.compute_payload_hash(content)
            try:
                is_cached, cached_response = idem_svc.start_or_get(
                    connector_key=connector_key,
                    idempotency_key=clean_idem_key,
                    payload_hash=payload_hash,
                )
            except IdempotencyConflictError as exc:
                duration_ms = get_duration_ms()
                logger.warning(
                    "Idempotency key conflict: reused with different request payload",
                    extra={
                        "event": "idempotency_conflict",
                        "connector_key": connector_key,
                        "method": "publish",
                        "operation": "publish",
                        "error_code": exc.error_code,
                        "duration_ms": duration_ms,
                        "idempotency_key": clean_idem_key,
                        "status_code": status.HTTP_409_CONFLICT,
                    },
                )
                raise

            if is_cached and cached_response is not None:
                duration_ms = get_duration_ms()
                is_async_job = "job_id" in cached_response and cached_response.get("status") in {
                    "queued",
                    "running",
                    "succeeded",
                    "failed",
                }
                status_code = status.HTTP_202_ACCEPTED if is_async_job else status.HTTP_200_OK
                logger.info(
                    "Idempotent response replayed from cache",
                    extra={
                        "event": "idempotency_replay",
                        "connector_key": connector_key,
                        "method": "publish",
                        "operation": "publish",
                        "duration_ms": duration_ms,
                        "post_id": cached_response.get("id") or cached_response.get("job_id"),
                        "idempotency_key": clean_idem_key,
                        "status_code": status_code,
                    },
                )
                if is_async_job:
                    return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=cached_response)
                return cached_response

            try:
                # 4a. Destination policy validation (text length, presence)
                policy_check = policy_svc.validate_content(connector_key, content)
                if not policy_check["valid"]:
                    idem_svc.cancel(connector_key, clean_idem_key)
                    duration_ms = get_duration_ms()
                    err_msg = policy_check["error"]
                    err_code = policy_check.get("error_code", ERROR_CODE_SPEC_VIOLATION)
                    logger.warning(
                        "Destination policy validation failed",
                        extra={
                            "event": "policy_validation_failure",
                            "connector_key": connector_key,
                            "method": "publish",
                            "operation": "publish",
                            "error_code": err_code,
                            "duration_ms": duration_ms,
                            "idempotency_key": clean_idem_key,
                            "status_code": status.HTTP_400_BAD_REQUEST,
                        },
                    )
                    return JSONResponse(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        content={
                            "error_code": err_code,
                            "shared_error_code": "DEST_SPEC_VIOLATION",
                            "code": "DEST_SPEC_VIOLATION",
                            "message": err_msg,
                            "detail": err_msg,
                            "error": err_msg,
                            "violations": [err_msg],
                        },
                    )

                # 4b. Frequency cap check
                freq_check = policy_svc.check_and_record_publish(connector_key)
                if not freq_check["allowed"]:
                    idem_svc.cancel(connector_key, clean_idem_key)
                    duration_ms = get_duration_ms()
                    err_msg = freq_check["error"]
                    err_code = freq_check.get("error_code", ERROR_CODE_FREQUENCY_CAP)
                    logger.warning(
                        "Publish frequency cap exceeded",
                        extra={
                            "event": "frequency_cap_exceeded",
                            "connector_key": connector_key,
                            "method": "publish",
                            "operation": "publish",
                            "error_code": err_code,
                            "duration_ms": duration_ms,
                            "idempotency_key": clean_idem_key,
                            "status_code": status.HTTP_429_TOO_MANY_REQUESTS,
                        },
                    )
                    return JSONResponse(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        content={
                            "error_code": err_code,
                            "shared_error_code": "DEST_RULE_FREQUENCY_CAP",
                            "code": "DEST_RULE_FREQUENCY_CAP",
                            "message": err_msg,
                            "detail": err_msg,
                            "error": err_msg,
                            "violations": [err_msg],
                        },
                    )

                # Asynchronous background execution
                if is_async:
                    job_svc = get_job_service()
                    job = job_svc.create_job(connector_key=connector_key, payload=content)
                    accepted_payload = {
                        "job_id": job.job_id,
                        "status": job.status.value,
                        "connector_key": connector_key,
                        "message": "Publish operation accepted for background processing.",
                        "status_url": f"/connector/v1/jobs/{job.job_id}",
                        "created_at": job.created_at,
                    }
                    idem_svc.complete(connector_key, clean_idem_key, accepted_payload)
                    background_tasks.add_task(
                        process_background_publish,
                        job.job_id,
                        connector_key,
                        content,
                        dest_config,
                        conn_obj,
                        delay_val,
                    )
                    duration_ms = get_duration_ms()
                    logger.info(
                        "Publish operation accepted for background processing",
                        extra={
                            "event": "job_enqueued",
                            "job_id": job.job_id,
                            "connector_key": connector_key,
                            "method": "publish",
                            "operation": "publish",
                            "duration_ms": duration_ms,
                            "idempotency_key": clean_idem_key,
                            "status_code": status.HTTP_202_ACCEPTED,
                        },
                    )
                    return JSONResponse(
                        status_code=status.HTTP_202_ACCEPTED,
                        content=accepted_payload,
                    )

                # 4c. Execute publishing synchronously
                raw_result = await _invoke_connector(
                    connector,
                    "publish",
                    content=content,
                    destination=dest_config,
                    connection=conn_obj,
                    idempotency_key=clean_idem_key,
                )
                if hasattr(raw_result, "model_dump"):
                    result = raw_result.model_dump()
                elif isinstance(raw_result, dict):
                    result = dict(raw_result)
                else:
                    result = {"success": True, "id": str(raw_result)}

                pid = str(result.get("platform_post_id") or result.get("id") or "post_1")
                url = str(result.get("live_url") or result.get("url") or "")
                status_str = str(result.get("status") or "published")

                result["platform_post_id"] = pid
                result["id"] = pid
                result["live_url"] = url
                result["url"] = url
                result["status"] = status_str
                if "success" not in result:
                    result["success"] = True
                result["destination"] = connector_key

                if not result.get("success"):
                    idem_svc.cancel(connector_key, clean_idem_key)
                    duration_ms = get_duration_ms()
                    err_msg = result.get("error", "Failed to publish content.")
                    logger.error(
                        "Connector publishing failed",
                        extra={
                            "event": "operation_failure",
                            "connector_key": connector_key,
                            "method": "publish",
                            "operation": "publish",
                            "error_code": ERROR_CODE_SPEC_VIOLATION,
                            "duration_ms": duration_ms,
                            "idempotency_key": clean_idem_key,
                            "status_code": status.HTTP_400_BAD_REQUEST,
                        },
                    )
                    return JSONResponse(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        content={
                            "error_code": ERROR_CODE_SPEC_VIOLATION,
                            "shared_error_code": "DEST_SPEC_VIOLATION",
                            "code": "DEST_SPEC_VIOLATION",
                            "message": err_msg,
                            "detail": err_msg,
                            "error": err_msg,
                        },
                    )

                idem_svc.complete(connector_key, clean_idem_key, result)
                duration_ms = get_duration_ms()
                logger.info(
                    "Connector operation completed successfully",
                    extra={
                        "event": "operation_success",
                        "connector_key": connector_key,
                        "method": "publish",
                        "operation": "publish",
                        "duration_ms": duration_ms,
                        "post_id": pid,
                        "idempotency_key": clean_idem_key,
                        "status_code": status.HTTP_200_OK,
                    },
                )
                return result
            except ConnectorException as exc:
                idem_svc.cancel(connector_key, clean_idem_key)
                duration_ms = get_duration_ms()
                logger.error(
                    f"Connector exception occurred: {exc.error_code}",
                    extra={
                        "event": "connector_exception",
                        "connector_key": connector_key,
                        "method": "publish",
                        "operation": "publish",
                        "error_code": exc.error_code,
                        "duration_ms": duration_ms,
                        "idempotency_key": clean_idem_key,
                        "status_code": exc.status_code,
                    },
                )
                raise
            except Exception:
                idem_svc.cancel(connector_key, clean_idem_key)
                raise

        # Path without idempotency key
        try:
            policy_check = policy_svc.validate_content(connector_key, content)
            if not policy_check["valid"]:
                duration_ms = get_duration_ms()
                err_msg = policy_check["error"]
                err_code = policy_check.get("error_code", ERROR_CODE_SPEC_VIOLATION)
                logger.warning(
                    "Destination policy validation failed",
                    extra={
                        "event": "policy_validation_failure",
                        "connector_key": connector_key,
                        "method": "publish",
                        "operation": "publish",
                        "error_code": err_code,
                        "duration_ms": duration_ms,
                        "status_code": status.HTTP_400_BAD_REQUEST,
                    },
                )
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={
                        "error_code": err_code,
                        "shared_error_code": "DEST_SPEC_VIOLATION",
                        "code": "DEST_SPEC_VIOLATION",
                        "message": err_msg,
                        "detail": err_msg,
                        "error": err_msg,
                    },
                )

            freq_check = policy_svc.check_and_record_publish(connector_key)
            if not freq_check["allowed"]:
                duration_ms = get_duration_ms()
                err_msg = freq_check["error"]
                err_code = freq_check.get("error_code", ERROR_CODE_FREQUENCY_CAP)
                logger.warning(
                    "Publish frequency cap exceeded",
                    extra={
                        "event": "frequency_cap_exceeded",
                        "connector_key": connector_key,
                        "method": "publish",
                        "operation": "publish",
                        "error_code": err_code,
                        "duration_ms": duration_ms,
                        "status_code": status.HTTP_429_TOO_MANY_REQUESTS,
                    },
                )
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={
                        "error_code": err_code,
                        "shared_error_code": "DEST_RULE_FREQUENCY_CAP",
                        "code": "DEST_RULE_FREQUENCY_CAP",
                        "message": err_msg,
                        "detail": err_msg,
                        "error": err_msg,
                    },
                )

            # Asynchronous execution without idempotency
            if is_async:
                job_svc = get_job_service()
                job = job_svc.create_job(connector_key=connector_key, payload=content)
                accepted_payload = {
                    "job_id": job.job_id,
                    "status": job.status.value,
                    "connector_key": connector_key,
                    "message": "Publish operation accepted for background processing.",
                    "status_url": f"/connector/v1/jobs/{job.job_id}",
                    "created_at": job.created_at,
                }
                background_tasks.add_task(
                    process_background_publish,
                    job.job_id,
                    connector_key,
                    content,
                    dest_config,
                    conn_obj,
                    delay_val,
                )
                duration_ms = get_duration_ms()
                logger.info(
                    "Publish operation accepted for background processing",
                    extra={
                        "event": "job_enqueued",
                        "job_id": job.job_id,
                        "connector_key": connector_key,
                        "method": "publish",
                        "operation": "publish",
                        "duration_ms": duration_ms,
                        "status_code": status.HTTP_202_ACCEPTED,
                    },
                )
                return JSONResponse(
                    status_code=status.HTTP_202_ACCEPTED,
                    content=accepted_payload,
                )

            raw_result = await _invoke_connector(
                connector,
                "publish",
                content=content,
                destination=dest_config,
                connection=conn_obj,
            )
            if hasattr(raw_result, "model_dump"):
                result = raw_result.model_dump()
            elif isinstance(raw_result, dict):
                result = dict(raw_result)
            else:
                result = {"success": True, "id": str(raw_result)}

            pid = str(result.get("platform_post_id") or result.get("id") or "post_1")
            url = str(result.get("live_url") or result.get("url") or "")
            status_str = str(result.get("status") or "published")

            result["platform_post_id"] = pid
            result["id"] = pid
            result["live_url"] = url
            result["url"] = url
            result["status"] = status_str
            if "success" not in result:
                result["success"] = True
            result["destination"] = connector_key

            if not result.get("success"):
                duration_ms = get_duration_ms()
                err_msg = result.get("error", "Failed to publish content.")
                logger.error(
                    "Connector publishing failed",
                    extra={
                        "event": "operation_failure",
                        "connector_key": connector_key,
                        "method": "publish",
                        "operation": "publish",
                        "error_code": ERROR_CODE_SPEC_VIOLATION,
                        "duration_ms": duration_ms,
                        "status_code": status.HTTP_400_BAD_REQUEST,
                    },
                )
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={
                        "error_code": ERROR_CODE_SPEC_VIOLATION,
                        "shared_error_code": "DEST_SPEC_VIOLATION",
                        "code": "DEST_SPEC_VIOLATION",
                        "message": err_msg,
                        "detail": err_msg,
                        "error": err_msg,
                    },
                )

            duration_ms = get_duration_ms()
            logger.info(
                "Connector operation completed successfully",
                extra={
                    "event": "operation_success",
                    "connector_key": connector_key,
                    "method": "publish",
                    "operation": "publish",
                    "duration_ms": duration_ms,
                    "post_id": pid,
                    "status_code": status.HTTP_200_OK,
                },
            )
            return result
        except ConnectorException as exc:
            duration_ms = get_duration_ms()
            logger.error(
                f"Connector exception occurred: {exc.error_code}",
                extra={
                    "event": "connector_exception",
                    "connector_key": connector_key,
                    "method": "publish",
                    "operation": "publish",
                    "error_code": exc.error_code,
                    "duration_ms": duration_ms,
                    "status_code": exc.status_code,
                },
            )
            raise

    # 5. Handle 'get_status'
    if norm_method == "get_status":
        post_id = req.get_effective_post_id()
        if not post_id or not str(post_id).strip():
            duration_ms = get_duration_ms()
            logger.warning(
                "Missing required 'post_id' field for get_status",
                extra={
                    "event": "missing_post_id",
                    "connector_key": connector_key,
                    "method": "get_status",
                    "operation": "get_status",
                    "duration_ms": duration_ms,
                    "status_code": status.HTTP_400_BAD_REQUEST,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Field 'post_id' or 'platform_post_id' is required for method 'get_status'.",
            )

        clean_pid = str(post_id).strip()
        raw_result = await _invoke_connector(
            connector,
            "get_status",
            platform_post_id=clean_pid,
            destination=dest_config,
            connection=conn_obj,
        )
        if hasattr(raw_result, "model_dump"):
            result = raw_result.model_dump()
        elif isinstance(raw_result, dict):
            result = dict(raw_result)
        else:
            result = {"status": "published", "platform_post_id": clean_pid}

        pid = str(result.get("platform_post_id") or result.get("id") or clean_pid)
        url = str(result.get("live_url") or result.get("url") or "")
        status_val = str(result.get("status") or "published")

        result["platform_post_id"] = pid
        result["id"] = pid
        result["live_url"] = url
        result["url"] = url
        result["status"] = status_val
        if "found" not in result:
            result["found"] = status_val not in ("not_found", "failed")

        duration_ms = get_duration_ms()
        if not result.get("found"):
            logger.warning(
                f"Post '{clean_pid}' not found",
                extra={
                    "event": "post_not_found",
                    "connector_key": connector_key,
                    "method": "get_status",
                    "operation": "get_status",
                    "duration_ms": duration_ms,
                    "post_id": clean_pid,
                    "status_code": status.HTTP_404_NOT_FOUND,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=result.get("error", f"Post '{clean_pid}' not found."),
            )

        logger.info(
            "Connector operation completed successfully",
            extra={
                "event": "operation_success",
                "connector_key": connector_key,
                "method": "get_status",
                "operation": "get_status",
                "duration_ms": duration_ms,
                "post_id": clean_pid,
                "status_code": status.HTTP_200_OK,
            },
        )
        return result

    # 6. Handle 'delete'
    if norm_method == "delete":
        post_id = req.get_effective_post_id()
        if not post_id or not str(post_id).strip():
            duration_ms = get_duration_ms()
            logger.warning(
                "Missing required 'post_id' field for delete",
                extra={
                    "event": "missing_post_id",
                    "connector_key": connector_key,
                    "method": "delete",
                    "operation": "delete",
                    "duration_ms": duration_ms,
                    "status_code": status.HTTP_400_BAD_REQUEST,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Field 'post_id' or 'platform_post_id' is required for method 'delete'.",
            )

        clean_pid = str(post_id).strip()
        raw_result = await _invoke_connector(
            connector,
            "delete",
            platform_post_id=clean_pid,
            destination=dest_config,
            connection=conn_obj,
        )
        if hasattr(raw_result, "model_dump"):
            result = raw_result.model_dump()
        elif isinstance(raw_result, dict):
            result = dict(raw_result)
        else:
            result = {"deleted": True, "success": True}

        del_ok = bool(result.get("deleted", result.get("success", True)))
        result["deleted"] = del_ok
        result["success"] = del_ok
        result["platform_post_id"] = str(result.get("platform_post_id") or result.get("id") or clean_pid)
        result["id"] = result["platform_post_id"]

        duration_ms = get_duration_ms()
        if not result.get("success"):
            logger.warning(
                f"Post '{clean_pid}' not found for deletion",
                extra={
                    "event": "post_not_found",
                    "connector_key": connector_key,
                    "method": "delete",
                    "operation": "delete",
                    "duration_ms": duration_ms,
                    "post_id": clean_pid,
                    "status_code": status.HTTP_404_NOT_FOUND,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=result.get("error", f"Post '{clean_pid}' not found."),
            )

        logger.info(
            "Connector operation completed successfully",
            extra={
                "event": "operation_success",
                "connector_key": connector_key,
                "method": "delete",
                "operation": "delete",
                "duration_ms": duration_ms,
                "post_id": clean_pid,
                "status_code": status.HTTP_200_OK,
            },
        )
        return result

    # Fallback
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Unhandled method '{method}'.",
    )
