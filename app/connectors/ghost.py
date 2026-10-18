"""
Ghost CMS Admin API connector implementation.

Follows the IncuBrix connector specification for Ghost publishing.
Supports Ghost Admin API v4/v5 with JWT HS256 token generation.
"""

import base64
import hashlib
import hmac
import json
import time
from typing import Any, Dict, Optional
import httpx

from app.connectors.base import BaseConnector
from app.models.errors import (
    ConnectorException,
    CANONICAL_DEST_SPEC_VIOLATION,
    CANONICAL_CONNECTION_AUTH_EXPIRED,
    CANONICAL_PLATFORM_RATE_LIMIT,
    CANONICAL_PLATFORM_CONTENT_REJECTED,
)
from app.models.payloads import ContentPayload, PublishResult
from app.models.policy import ValidationResult


def _generate_ghost_jwt(admin_api_key: str) -> str:
    """Generate Ghost Admin API JWT token using HS256 without external jwt libraries."""
    try:
        key_id, secret = admin_api_key.split(":")
    except ValueError:
        raise ConnectorException(
            "Ghost Admin API key must be in format {id}:{secret}.",
            status_code=401,
            error_code=CANONICAL_CONNECTION_AUTH_EXPIRED,
            canonical_code=CANONICAL_CONNECTION_AUTH_EXPIRED,
        )

    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT", "kid": key_id}
    payload = {"iat": now, "exp": now + 300, "aud": "/admin/"}

    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")

    header_b64 = b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")

    secret_bytes = bytes.fromhex(secret)
    signature = hmac.new(secret_bytes, signing_input, hashlib.sha256).digest()
    sig_b64 = b64url(signature)

    return f"{header_b64}.{payload_b64}.{sig_b64}"


class GhostConnector(BaseConnector):
    """Ghost CMS Admin API connector."""

    name = "ghost"

    def get_manifest(self) -> Dict[str, Any]:
        return {
            "key": "ghost",
            "name": "Ghost CMS",
            "version": "1.0.0",
            "tier": "tier_1",
            "auth": {
                "type": "admin_api_key",
                "format": "id:secret",
                "header": "Authorization: Ghost {jwt}",
            },
            "surfaces": ["post", "page"],
            "content_types": ["html", "lexical", "markdown"],
            "specification_limits": {
                "max_title_length": 255,
                "max_body_length": 500000,
            },
            "rate_limits": {
                "requests_per_minute": 60,
            },
            "capabilities": {
                "publish": True,
                "get_status": True,
                "delete": True,
                "fetch_metrics": True,
                "refresh_auth": False,
                "build_assist_pack": False,
            },
            "error_map": {
                "400": CANONICAL_DEST_SPEC_VIOLATION,
                "401": CANONICAL_CONNECTION_AUTH_EXPIRED,
                "403": CANONICAL_CONNECTION_AUTH_EXPIRED,
                "422": CANONICAL_PLATFORM_CONTENT_REJECTED,
                "429": CANONICAL_PLATFORM_RATE_LIMIT,
            },
        }

    def validate(self, payload: ContentPayload) -> ValidationResult:
        errors = []
        text = payload.text or ""
        title = payload.title or ""

        if not text.strip():
            errors.append("Ghost post content cannot be empty.")
        if len(text) > 500000:
            errors.append("Ghost post content exceeds maximum length of 500,000 characters.")
        if title and len(title) > 255:
            errors.append("Ghost post title exceeds maximum length of 255 characters.")

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            ok=len(errors) == 0,
            violations=errors,
        )

    def _get_auth_headers(self, connection: Dict[str, Any]) -> Dict[str, str]:
        admin_key = (
            connection.get("admin_api_key")
            or connection.get("api_key")
            or connection.get("token")
        )
        if not admin_key:
            raise ConnectorException(
                "Missing Ghost Admin API key in connection.",
                status_code=401,
                error_code=CANONICAL_CONNECTION_AUTH_EXPIRED,
                canonical_code=CANONICAL_CONNECTION_AUTH_EXPIRED,
            )
        jwt_token = _generate_ghost_jwt(str(admin_key))
        return {
            "Authorization": f"Ghost {jwt_token}",
            "Content-Type": "application/json",
            "Accept-Version": "v5.0",
        }

    def _get_base_url(self, destination: Dict[str, Any]) -> str:
        base_url = destination.get("base_url") or destination.get("instance_url") or destination.get("site_url")
        if not base_url:
            raise ConnectorException(
                "Missing Ghost base_url or site_url in destination config.",
                status_code=400,
                error_code=CANONICAL_DEST_SPEC_VIOLATION,
                canonical_code=CANONICAL_DEST_SPEC_VIOLATION,
            )
        return str(base_url).rstrip("/")

    async def publish(
        self,
        payload: ContentPayload,
        destination: Dict[str, Any],
        connection: Dict[str, Any],
        idempotency_key: Optional[str] = None,
    ) -> PublishResult:
        if connection.get("simulation") or destination.get("simulation"):
            sim_id = f"sim_ghost_{idempotency_key or 'post'}"
            base = destination.get("base_url", "https://demo.ghost.io").rstrip("/")
            return PublishResult(
                platform_post_id=sim_id,
                url=f"{base}/simulated-post-{sim_id}",
                status="published",
                metadata={"simulation": True, "connector": "ghost"},
            )

        val = self.validate(payload)
        if not val.valid:
            raise ConnectorException(
                f"Validation failed: {', '.join(val.errors)}",
                status_code=400,
                error_code=CANONICAL_DEST_SPEC_VIOLATION,
                canonical_code=CANONICAL_DEST_SPEC_VIOLATION,
                details={"violations": val.violations},
            )

        base_url = self._get_base_url(destination)
        headers = self._get_auth_headers(connection)

        status_flag = destination.get("status", "published")
        title = payload.title or payload.text[:60].strip() or "Untitled Post"

        # Ghost supports html post source
        post_obj: Dict[str, Any] = {
            "title": title,
            "html": f"<p>{payload.text}</p>",
            "status": status_flag,
        }

        tags = payload.metadata.get("tags") if payload.metadata else None
        if tags and isinstance(tags, list):
            post_obj["tags"] = [{"name": t} for t in tags]

        url = f"{base_url}/ghost/api/admin/posts/?source=html"

        async with httpx.AsyncClient(timeout=20.0) as client:
            try:
                resp = await client.post(url, json={"posts": [post_obj]}, headers=headers)
            except httpx.RequestError as exc:
                raise ConnectorException(
                    f"Ghost network error: {str(exc)}",
                    status_code=503,
                    error_code="PLATFORM_UNAVAILABLE",
                    retryable=True,
                )

        if resp.status_code in (401, 403):
            raise ConnectorException(
                "Ghost authentication failed.",
                status_code=401,
                error_code=CANONICAL_CONNECTION_AUTH_EXPIRED,
                canonical_code=CANONICAL_CONNECTION_AUTH_EXPIRED,
            )
        elif resp.status_code == 422:
            raise ConnectorException(
                f"Ghost rejected content: {resp.text}",
                status_code=422,
                error_code=CANONICAL_PLATFORM_CONTENT_REJECTED,
                canonical_code=CANONICAL_PLATFORM_CONTENT_REJECTED,
            )
        elif resp.status_code == 429:
            raise ConnectorException(
                "Ghost rate limit exceeded.",
                status_code=429,
                error_code=CANONICAL_PLATFORM_RATE_LIMIT,
                canonical_code=CANONICAL_PLATFORM_RATE_LIMIT,
                retryable=True,
            )
        elif resp.status_code not in (200, 201):
            raise ConnectorException(
                f"Ghost publish failed with status {resp.status_code}: {resp.text}",
                status_code=resp.status_code,
                error_code="PLATFORM_ERROR",
            )

        data = resp.json()
        posts = data.get("posts", [])
        if not posts:
            raise ConnectorException(
                "Ghost response contained empty post list.",
                status_code=500,
                error_code="PLATFORM_ERROR",
            )
        created = posts[0]
        post_id = str(created.get("id"))
        post_url = created.get("url") or f"{base_url}/{created.get('slug', post_id)}"

        return PublishResult(
            platform_post_id=post_id,
            url=post_url,
            status=created.get("status", "published"),
            metadata={"ghost_id": post_id, "slug": created.get("slug"), "uuid": created.get("uuid")},
        )

    async def get_status(
        self,
        platform_post_id: str,
        destination: Dict[str, Any],
        connection: Dict[str, Any],
    ) -> Dict[str, Any]:
        if connection.get("simulation") or destination.get("simulation") or platform_post_id.startswith("sim_"):
            return {
                "status": "published",
                "live_url": f"{destination.get('base_url', 'https://demo.ghost.io')}/simulated-{platform_post_id}",
                "platform_post_id": platform_post_id,
                "simulation": True,
            }

        base_url = self._get_base_url(destination)
        headers = self._get_auth_headers(connection)
        url = f"{base_url}/ghost/api/admin/posts/{platform_post_id}/"

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.get(url, headers=headers)
            except httpx.RequestError as exc:
                raise ConnectorException(
                    f"Ghost network error: {str(exc)}",
                    status_code=503,
                    error_code="PLATFORM_UNAVAILABLE",
                    retryable=True,
                )

        if resp.status_code == 404:
            return {"status": "not_found", "platform_post_id": platform_post_id}
        elif resp.status_code != 200:
            raise ConnectorException(
                f"Ghost get_status failed: {resp.text}",
                status_code=resp.status_code,
                error_code="PLATFORM_ERROR",
            )

        posts = resp.json().get("posts", [])
        if not posts:
            return {"status": "not_found", "platform_post_id": platform_post_id}

        post = posts[0]
        return {
            "status": post.get("status", "published"),
            "live_url": post.get("url"),
            "platform_post_id": str(post.get("id")),
            "title": post.get("title"),
            "published_at": post.get("published_at"),
        }

    async def delete(
        self,
        platform_post_id: str,
        destination: Dict[str, Any],
        connection: Dict[str, Any],
    ) -> Dict[str, Any]:
        if connection.get("simulation") or destination.get("simulation") or platform_post_id.startswith("sim_"):
            return {"deleted": True, "platform_post_id": platform_post_id, "simulation": True}

        base_url = self._get_base_url(destination)
        headers = self._get_auth_headers(connection)
        url = f"{base_url}/ghost/api/admin/posts/{platform_post_id}/"

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.delete(url, headers=headers)
            except httpx.RequestError as exc:
                raise ConnectorException(
                    f"Ghost network error: {str(exc)}",
                    status_code=503,
                    error_code="PLATFORM_UNAVAILABLE",
                    retryable=True,
                )

        if resp.status_code in (200, 204):
            return {"deleted": True, "platform_post_id": platform_post_id}
        elif resp.status_code == 404:
            return {"deleted": True, "platform_post_id": platform_post_id, "note": "Post was already absent."}
        else:
            raise ConnectorException(
                f"Ghost delete failed: {resp.text}",
                status_code=resp.status_code,
                error_code="PLATFORM_ERROR",
            )

    async def fetch_metrics(
        self,
        platform_post_id: str,
        destination: Dict[str, Any],
        connection: Dict[str, Any],
        since: Optional[str] = None,
    ) -> Dict[str, Any]:
        if connection.get("simulation") or destination.get("simulation") or platform_post_id.startswith("sim_"):
            return {
                "platform_post_id": platform_post_id,
                "views": 150,
                "reactions": 0,
                "comments": 0,
                "shares": 0,
                "simulation": True,
            }

        status_data = await self.get_status(platform_post_id, destination, connection)
        return {
            "platform_post_id": platform_post_id,
            "views": 0,
            "reactions": 0,
            "comments": 0,
            "shares": 0,
            "status": status_data.get("status"),
        }
