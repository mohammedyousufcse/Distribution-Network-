"""Lemmy destination connector implementing the BaseConnector interface."""

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

logger = get_logger("app.connectors.lemmy")

LEMMY_MAX_LENGTH = 10000
LEMMY_MAX_TITLE_LENGTH = 200


class LemmyConnector(BaseConnector):
    """Production connector for Lemmy federated communities via official Lemmy REST API."""

    def __init__(
        self,
        instance_url: Optional[str] = None,
        auth_token: Optional[str] = None,
        community_id: Optional[int] = None,
        http_client: Optional[httpx.Client] = None,
        timeout: float = 10.0,
    ) -> None:
        self._explicit_instance_url = instance_url
        self._explicit_auth_token = auth_token
        self._explicit_community_id = community_id
        self._client = http_client
        self.timeout = timeout

    def get_manifest(self) -> Dict[str, Any]:
        """Return manifest for Lemmy destination connector."""
        return {
            "key": "lemmy",
            "version": "1.0.0",
            "tier": "core",
            "auth": "jwt",
            "surfaces": ["community_post"],
            "content_types": ["text/markdown", "text/plain"],
            "specification_limits": {
                "max_text_length": LEMMY_MAX_LENGTH,
                "max_title_length": LEMMY_MAX_TITLE_LENGTH,
                "min_text_length": 1,
            },
            "rate_limits": {
                "requests_per_minute": 15,
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
            "instance_parameter": "instance_url",
        }

    def _resolve_config(self, connection: Optional[Dict[str, Any]] = None, destination: Optional[Dict[str, Any]] = None) -> tuple[str, str, int]:
        conn = connection or {}
        dest = destination or {}

        instance_url = (
            conn.get("instance_url")
            or dest.get("instance_url")
            or dest.get("base_url")
            or self._explicit_instance_url
            or "https://lemmy.world"
        ).strip().rstrip("/")

        token = conn.get("auth_token") or conn.get("token") or self._explicit_auth_token or ""
        community_id = conn.get("community_id") or dest.get("community_id") or self._explicit_community_id or 1

        return instance_url, str(token).strip(), int(community_id)

    def _get_http_client(self) -> httpx.Client:
        if self._client is not None:
            return self._client
        return httpx.Client(timeout=self.timeout)

    def validate(self, content: Any, **kwargs: Any) -> Any:
        """Validate content payload against Lemmy limits."""
        from app.models.policy import PolicyValidationResult

        if hasattr(content, "model_dump"):
            content = content.model_dump()
        elif not isinstance(content, dict):
            return PolicyValidationResult(valid=False, ok=False, error="Content must be a dictionary.", violations=["Content must be a dictionary."])

        text = content.get("text") or content.get("body") or ""
        title = content.get("title") or content.get("name") or (text.strip().split("\n")[0][:LEMMY_MAX_TITLE_LENGTH] if text else "")

        if not str(title).strip():
            msg = "Lemmy post requires a non-empty title/name."
            return PolicyValidationResult(valid=False, ok=False, error=msg, violations=[msg])

        if len(str(title)) > LEMMY_MAX_TITLE_LENGTH:
            msg = f"Lemmy post title exceeds {LEMMY_MAX_TITLE_LENGTH} characters."
            return PolicyValidationResult(valid=False, ok=False, error=msg, violations=[msg])

        if len(str(text)) > LEMMY_MAX_LENGTH:
            msg = f"Lemmy post body exceeds {LEMMY_MAX_LENGTH} characters."
            return PolicyValidationResult(valid=False, ok=False, error=msg, violations=[msg])

        return PolicyValidationResult(valid=True, ok=True, violations=[])

    def publish(self, content: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        """Publish post to Lemmy via POST /api/v3/post."""
        validation = self.validate(content)
        if not validation["ok"]:
            return {"success": False, "ok": False, "error": validation["error"], "violations": validation.get("violations", [])}

        connection = kwargs.get("connection") or {}
        destination = kwargs.get("destination") or {}

        if connection.get("simulation") or destination.get("simulation") or (isinstance(content, dict) and content.get("simulation")):
            sim_id = f"sim_lemmy_{kwargs.get('idempotency_key') or 'post'}"
            instance_url = (destination.get("instance_url") or destination.get("base_url") or "https://lemmy.world").strip().rstrip("/")
            return {
                "success": True,
                "id": sim_id,
                "platform_post_id": sim_id,
                "url": f"{instance_url}/post/{sim_id}",
                "live_url": f"{instance_url}/post/{sim_id}",
                "status": "published",
                "simulation": True,
            }

        instance_url, token, community_id = self._resolve_config(connection, destination)

        text = str(content.get("text") or content.get("body") or "").strip()
        title = str(content.get("title") or content.get("name") or text.split("\n")[0][:100]).strip()

        payload: Dict[str, Any] = {
            "name": title,
            "body": text,
            "community_id": community_id,
        }
        if token:
            payload["auth"] = token
        if "url" in content:
            payload["url"] = content["url"]

        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        client = self._get_http_client()
        should_close = self._client is None

        try:
            response = client.post(f"{instance_url}/api/v3/post", json=payload, headers=headers)
            if response.status_code in (200, 201):
                data = response.json()
                post_data = data.get("post_view", {}).get("post", {})
                post_id = str(post_data.get("id") or data.get("id", "lemmy_post"))
                live_url = post_data.get("ap_id") or f"{instance_url}/post/{post_id}"
                created_at = post_data.get("published") or datetime.now(timezone.utc).isoformat()

                return {
                    "success": True,
                    "ok": True,
                    "id": post_id,
                    "platform_post_id": post_id,
                    "status": "published",
                    "destination": "lemmy",
                    "url": live_url,
                    "live_url": live_url,
                    "created_at": created_at,
                    "message": "Post successfully published to Lemmy.",
                }
            self._handle_error(response)
        except (AuthExpiredError, RateLimitedError, ContentRejectedError, ForbiddenError, DestinationSpecViolationError, DestinationError, NetworkError):
            raise
        except httpx.TimeoutException as exc:
            raise NetworkError(f"Request to Lemmy timed out: {exc}") from exc
        except httpx.RequestError as exc:
            raise NetworkError(f"Network error contacting Lemmy: {exc}") from exc
        finally:
            if should_close:
                client.close()

    def get_status(self, post_id: str, **kwargs: Any) -> Dict[str, Any]:
        """Retrieve post details via GET /api/v3/post?id={id}."""
        connection = kwargs.get("connection") or {}
        destination = kwargs.get("destination") or {}

        if connection.get("simulation") or destination.get("simulation") or str(post_id).startswith("sim_"):
            instance_url = (destination.get("instance_url") or destination.get("base_url") or "https://lemmy.world").strip().rstrip("/")
            return {
                "found": True,
                "status": "published",
                "id": str(post_id),
                "platform_post_id": str(post_id),
                "live_url": f"{instance_url}/post/{post_id}",
                "url": f"{instance_url}/post/{post_id}",
                "simulation": True,
            }

        instance_url, token, _ = self._resolve_config(connection, destination)

        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        client = self._get_http_client()
        should_close = self._client is None

        try:
            response = client.get(f"{instance_url}/api/v3/post", params={"id": post_id}, headers=headers)
            if response.status_code == 200:
                data = response.json()
                post_view = data.get("post_view", {})
                post_data = post_view.get("post", {})
                counts = post_view.get("counts", {})
                live_url = post_data.get("ap_id") or f"{instance_url}/post/{post_id}"

                return {
                    "found": True,
                    "id": str(post_id),
                    "platform_post_id": str(post_id),
                    "status": "published",
                    "live_url": live_url,
                    "url": live_url,
                    "score": counts.get("score", 0),
                    "upvotes": counts.get("upvotes", 0),
                    "comments": counts.get("comments", 0),
                    "created_at": post_data.get("published"),
                }
            if response.status_code == 404:
                return {"found": False, "id": str(post_id), "status": "not_found", "error": f"Lemmy post '{post_id}' not found."}
            self._handle_error(response)
        finally:
            if should_close:
                client.close()

    def delete(self, post_id: str, **kwargs: Any) -> Dict[str, Any]:
        """Delete post via POST /api/v3/post/delete."""
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

        instance_url, token, _ = self._resolve_config(connection, destination)

        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        clean_id = int(post_id) if str(post_id).isdigit() else 1
        payload = {"post_id": clean_id, "deleted": True}
        if token:
            payload["auth"] = token

        client = self._get_http_client()
        should_close = self._client is None

        try:
            response = client.post(f"{instance_url}/api/v3/post/delete", json=payload, headers=headers)
            if response.status_code == 200:
                return {"success": True, "deleted": True, "id": str(post_id), "message": f"Lemmy post '{post_id}' deleted."}
            if response.status_code == 404:
                return {"success": False, "deleted": False, "id": str(post_id), "error": f"Lemmy post '{post_id}' not found."}
            self._handle_error(response)
        finally:
            if should_close:
                client.close()

    def fetch_metrics(self, post_id: str, connection: Optional[Dict[str, Any]] = None, since: Optional[str] = None) -> Dict[str, Any]:
        """Fetch normalized post metrics (upvotes, score, comments)."""
        status_res = self.get_status(post_id, connection=connection)
        if status_res.get("found"):
            return {
                "supported": True,
                "post_id": str(post_id),
                "metrics": {
                    "upvotes": status_res.get("upvotes", 0),
                    "score": status_res.get("score", 0),
                    "comments": status_res.get("comments", 0),
                },
            }
        return {"supported": False, "post_id": str(post_id), "error": "Post not found"}

    def _handle_error(self, response: httpx.Response) -> None:
        status_code = response.status_code
        try:
            body = response.json()
            err_msg = body.get("error") or response.text[:200]
        except Exception:
            err_msg = response.text[:200]

        if status_code == 401:
            raise AuthExpiredError(f"Lemmy auth failed: {err_msg}")
        if status_code == 403:
            raise ContentRejectedError(f"Lemmy permission/content rejected: {err_msg}")
        if status_code in (400, 422):
            raise DestinationSpecViolationError(f"Lemmy rejected post content: {err_msg}")
        if status_code == 429:
            raise RateLimitedError(f"Lemmy rate limited: {err_msg}")
        raise DestinationError(f"Lemmy API error ({status_code}): {err_msg}")
