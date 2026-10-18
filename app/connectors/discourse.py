"""Discourse destination connector implementing the BaseConnector interface."""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import httpx

from app.connectors.base import BaseConnector
from app.logging import get_logger
from app.models.errors import (
    CONNECTION_AUTH_EXPIRED,
    DEST_SPEC_VIOLATION,
    PLATFORM_CONTENT_REJECTED,
    PLATFORM_RATE_LIMIT,
    AuthExpiredError,
    ContentRejectedError,
    DestinationError,
    DestinationSpecViolationError,
    ForbiddenError,
    NetworkError,
    RateLimitedError,
)

logger = get_logger("app.connectors.discourse")

DISCOURSE_MAX_LENGTH = 32000
DISCOURSE_MIN_BODY_LENGTH = 20
DISCOURSE_MIN_TITLE_LENGTH = 10


class DiscourseConnector(BaseConnector):
    """Production connector for Discourse community forums via official REST API."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        api_username: Optional[str] = None,
        category_id: Optional[int] = None,
        http_client: Optional[httpx.Client] = None,
        timeout: float = 10.0,
    ) -> None:
        self._explicit_base_url = base_url
        self._explicit_api_key = api_key
        self._explicit_api_username = api_username
        self._explicit_category_id = category_id
        self._client = http_client
        self.timeout = timeout

    def get_manifest(self) -> Dict[str, Any]:
        """Return manifest for Discourse destination connector."""
        return {
            "key": "discourse",
            "version": "1.0.0",
            "tier": "core",
            "auth": "api_key",
            "surfaces": ["topic", "forum_topic", "forum_post"],
            "content_types": ["text/markdown", "text/plain"],
            "specification_limits": {
                "max_text_length": DISCOURSE_MAX_LENGTH,
                "min_text_length": DISCOURSE_MIN_BODY_LENGTH,
                "min_title_length": DISCOURSE_MIN_TITLE_LENGTH,
            },
            "rate_limits": {
                "requests_per_minute": 20,
            },
            "capabilities": {
                "validate": True,
                "publish": True,
                "get_status": True,
                "delete": True,
                "fetch_metrics": True,
                "refresh_auth": False,
                "build_assist_pack": False,
            },
            "error_map": {
                "401": CONNECTION_AUTH_EXPIRED,
                "403": PLATFORM_CONTENT_REJECTED,
                "422": DEST_SPEC_VIOLATION,
                "429": PLATFORM_RATE_LIMIT,
            },
            "instance_parameter": "base_url",
        }

    def _resolve_config(self, connection: Optional[Dict[str, Any]] = None, destination: Optional[Dict[str, Any]] = None) -> tuple[str, str, str, Optional[int]]:
        """Resolve base_url, api_key, api_username, and category_id."""
        conn = connection or {}
        dest = destination or {}

        base_url = (
            conn.get("base_url")
            or dest.get("base_url")
            or dest.get("instance_url")
            or self._explicit_base_url
            or "https://meta.discourse.org"
        ).strip().rstrip("/")

        api_key = conn.get("api_key") or self._explicit_api_key or ""
        api_username = conn.get("api_username") or self._explicit_api_username or "system"
        category = conn.get("category_id") or dest.get("category_id") or self._explicit_category_id

        return base_url, str(api_key).strip(), str(api_username).strip(), category

    def _get_http_client(self) -> httpx.Client:
        if self._client is not None:
            return self._client
        return httpx.Client(timeout=self.timeout)

    def validate(self, content: Any, **kwargs: Any) -> Any:
        """Validate content against Discourse topic creation rules."""
        from app.models.policy import PolicyValidationResult

        if hasattr(content, "model_dump"):
            content = content.model_dump()
        elif not isinstance(content, dict):
            return PolicyValidationResult(valid=False, ok=False, error="Content must be a dictionary.", violations=["Content must be a dictionary."])

        text = content.get("text") or content.get("raw") or ""
        if not isinstance(text, str) or not text.strip():
            msg = "Discourse post body must contain non-empty text."
            return PolicyValidationResult(valid=False, ok=False, error=msg, violations=[msg])

        title = content.get("title")
        if not title:
            # Fall back to first line if title not explicitly provided
            lines = text.strip().split("\n")
            title = lines[0][:100]

        if len(str(title).strip()) < DISCOURSE_MIN_TITLE_LENGTH:
            msg = f"Discourse topic title must be at least {DISCOURSE_MIN_TITLE_LENGTH} characters."
            return PolicyValidationResult(valid=False, ok=False, error=msg, violations=[msg])

        if len(text.strip()) < DISCOURSE_MIN_BODY_LENGTH:
            msg = f"Discourse post body must be at least {DISCOURSE_MIN_BODY_LENGTH} characters."
            return PolicyValidationResult(valid=False, ok=False, error=msg, violations=[msg])

        if len(text) > DISCOURSE_MAX_LENGTH:
            msg = f"Discourse post exceeds maximum length of {DISCOURSE_MAX_LENGTH} characters."
            return PolicyValidationResult(valid=False, ok=False, error=msg, violations=[msg])

        return PolicyValidationResult(valid=True, ok=True, violations=[])

    def publish(self, content: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        """Publish topic/post to Discourse via POST /posts.json."""
        validation = self.validate(content)
        if not validation["ok"]:
            return {"success": False, "ok": False, "error": validation["error"], "violations": validation.get("violations", [])}

        connection = kwargs.get("connection") or {}
        destination = kwargs.get("destination") or {}

        if connection.get("simulation") or destination.get("simulation") or (isinstance(content, dict) and content.get("simulation")):
            sim_id = f"sim_disc_{kwargs.get('idempotency_key') or 'post'}"
            base_url = destination.get("base_url") or "https://meta.discourse.org"
            return {
                "success": True,
                "id": sim_id,
                "platform_post_id": sim_id,
                "url": f"{base_url}/t/topic/{sim_id}",
                "live_url": f"{base_url}/t/topic/{sim_id}",
                "status": "published",
                "simulation": True,
            }

        base_url, api_key, api_username, category_id = self._resolve_config(connection, destination)

        text = str(content.get("text") or content.get("raw")).strip()
        title = content.get("title") or text.split("\n")[0][:100]

        payload: Dict[str, Any] = {
            "title": str(title).strip(),
            "raw": text,
        }
        if category_id:
            payload["category"] = category_id
        if "tags" in content and isinstance(content["tags"], list):
            payload["tags"] = content["tags"]

        headers = {
            "Api-Key": api_key,
            "Api-Username": api_username,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        client = self._get_http_client()
        should_close = self._client is None

        try:
            response = client.post(f"{base_url}/posts.json", json=payload, headers=headers)
            if response.status_code in (200, 201):
                data = response.json()
                post_id = str(data.get("id"))
                topic_id = str(data.get("topic_id", post_id))
                topic_slug = data.get("topic_slug", "topic")
                live_url = f"{base_url}/t/{topic_slug}/{topic_id}"
                created_at = data.get("created_at") or datetime.now(timezone.utc).isoformat()

                return {
                    "success": True,
                    "ok": True,
                    "id": post_id,
                    "platform_post_id": post_id,
                    "topic_id": topic_id,
                    "status": "published",
                    "destination": "discourse",
                    "url": live_url,
                    "live_url": live_url,
                    "created_at": created_at,
                    "message": "Topic successfully created on Discourse.",
                }
            self._handle_error(response)
        except (AuthExpiredError, RateLimitedError, ContentRejectedError, ForbiddenError, DestinationSpecViolationError, DestinationError, NetworkError):
            raise
        except httpx.TimeoutException as exc:
            raise NetworkError(f"Request to Discourse timed out: {exc}") from exc
        except httpx.RequestError as exc:
            raise NetworkError(f"Network error contacting Discourse: {exc}") from exc
        finally:
            if should_close:
                client.close()

    def get_status(self, post_id: str, **kwargs: Any) -> Dict[str, Any]:
        """Retrieve post status via GET /posts/{id}.json."""
        connection = kwargs.get("connection") or {}
        destination = kwargs.get("destination") or {}

        if connection.get("simulation") or destination.get("simulation") or str(post_id).startswith("sim_"):
            base_url = destination.get("base_url") or "https://meta.discourse.org"
            return {
                "found": True,
                "status": "published",
                "id": str(post_id),
                "platform_post_id": str(post_id),
                "live_url": f"{base_url}/t/topic/{post_id}",
                "url": f"{base_url}/t/topic/{post_id}",
                "simulation": True,
            }

        base_url, api_key, api_username, _ = self._resolve_config(connection, destination)

        headers = {"Api-Key": api_key, "Api-Username": api_username, "Accept": "application/json"}
        client = self._get_http_client()
        should_close = self._client is None

        try:
            response = client.get(f"{base_url}/posts/{post_id}.json", headers=headers)
            if response.status_code == 200:
                data = response.json()
                topic_id = str(data.get("topic_id", post_id))
                topic_slug = data.get("topic_slug", "topic")
                live_url = f"{base_url}/t/{topic_slug}/{topic_id}"
                return {
                    "found": True,
                    "id": str(post_id),
                    "platform_post_id": str(post_id),
                    "status": "published",
                    "live_url": live_url,
                    "url": live_url,
                    "reads": data.get("reads", 0),
                    "like_count": data.get("like_count", 0),
                    "reply_count": data.get("reply_count", 0),
                    "created_at": data.get("created_at"),
                }
            if response.status_code == 404:
                return {"found": False, "id": str(post_id), "status": "not_found", "error": f"Discourse post '{post_id}' not found."}
            self._handle_error(response)
        finally:
            if should_close:
                client.close()

    def delete(self, post_id: str, **kwargs: Any) -> Dict[str, Any]:
        """Delete post via DELETE /posts/{id}.json."""
        connection = kwargs.get("connection") or {}
        destination = kwargs.get("destination") or {}

        if connection.get("simulation") or destination.get("simulation") or str(post_id).startswith("sim_"):
            return {
                "success": True,
                "deleted": True,
                "id": str(post_id),
                "platform_post_id": str(post_id),
                "simulation": True,
            }

        base_url, api_key, api_username, _ = self._resolve_config(connection, destination)

        headers = {"Api-Key": api_key, "Api-Username": api_username, "Accept": "application/json"}
        client = self._get_http_client()
        should_close = self._client is None

        try:
            response = client.delete(f"{base_url}/posts/{post_id}.json", headers=headers)
            if response.status_code in (200, 204):
                return {"success": True, "deleted": True, "id": str(post_id), "message": f"Discourse post '{post_id}' deleted."}
            if response.status_code == 404:
                return {"success": False, "deleted": False, "id": str(post_id), "error": f"Discourse post '{post_id}' not found."}
            self._handle_error(response)
        finally:
            if should_close:
                client.close()

    def fetch_metrics(self, post_id: str, connection: Optional[Dict[str, Any]] = None, since: Optional[str] = None) -> Dict[str, Any]:
        """Fetch normalized post metrics (reads, likes, replies)."""
        status_res = self.get_status(post_id, connection=connection)
        if status_res.get("found"):
            return {
                "supported": True,
                "post_id": str(post_id),
                "metrics": {
                    "views": status_res.get("reads", 0),
                    "likes": status_res.get("like_count", 0),
                    "replies": status_res.get("reply_count", 0),
                },
            }
        return {"supported": False, "post_id": str(post_id), "error": "Post not found"}

    def _handle_error(self, response: httpx.Response) -> None:
        status_code = response.status_code
        try:
            body = response.json()
            err_msg = body.get("errors") or body.get("error") or response.text[:200]
            if isinstance(err_msg, list):
                err_msg = ", ".join(str(e) for e in err_msg)
        except Exception:
            err_msg = response.text[:200]

        if status_code in (401, 403):
            lower = str(err_msg).lower()
            if "forbidden" in lower or "permission" in lower:
                raise ForbiddenError(f"Discourse permission error: {err_msg}")
            raise AuthExpiredError(f"Discourse auth failed: {err_msg}")
        if status_code == 422:
            raise DestinationSpecViolationError(f"Discourse rejected content: {err_msg}")
        if status_code == 429:
            raise RateLimitedError(f"Discourse rate limited: {err_msg}")
        raise DestinationError(f"Discourse API error ({status_code}): {err_msg}")
