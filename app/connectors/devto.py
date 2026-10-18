"""
Dev.to (Forem) API connector implementation.

Follows the IncuBrix connector specification for Dev.to article publishing.
Uses Forem /api/articles REST API.
"""

from typing import Any, Dict, Optional
import httpx

from app.connectors.base import BaseConnector
from app.models.errors import (
    ConnectorException,
    CANONICAL_DEST_SPEC_VIOLATION,
    CANONICAL_CONNECTION_AUTH_EXPIRED,
    CANONICAL_PLATFORM_RATE_LIMIT,
    CANONICAL_PLATFORM_QUOTA_EXHAUSTED,
    CANONICAL_PLATFORM_CONTENT_REJECTED,
)
from app.models.payloads import ContentPayload, PublishResult
from app.models.policy import ValidationResult


class DevtoConnector(BaseConnector):
    """Dev.to connector using the Forem API."""

    name = "devto"
    DEFAULT_BASE_URL = "https://dev.to/api"

    def get_manifest(self) -> Dict[str, Any]:
        return {
            "key": "devto",
            "name": "Dev.to (Forem)",
            "version": "1.0.0",
            "tier": "tier_1",
            "auth": {
                "type": "api_key",
                "header": "api-key",
            },
            "surfaces": ["article"],
            "content_types": ["markdown"],
            "specification_limits": {
                "max_title_length": 128,
                "max_body_length": 100000,
                "max_tags": 4,
            },
            "rate_limits": {
                "requests_per_minute": 30,
            },
            "capabilities": {
                "publish": True,
                "get_status": True,
                "delete": True,  # Via unpublishing or API if supported
                "fetch_metrics": True,
                "refresh_auth": False,
                "build_assist_pack": False,
            },
            "error_map": {
                "400": CANONICAL_DEST_SPEC_VIOLATION,
                "401": CANONICAL_CONNECTION_AUTH_EXPIRED,
                "422": CANONICAL_PLATFORM_CONTENT_REJECTED,
                "429": CANONICAL_PLATFORM_RATE_LIMIT,
            },
        }

    def validate(self, payload: ContentPayload) -> ValidationResult:
        errors = []
        text = payload.text or ""
        title = payload.title or ""

        if not text.strip():
            errors.append("Article body text cannot be empty.")
        if len(text) > 100000:
            errors.append("Article body exceeds maximum length of 100,000 characters.")
        if title and len(title) > 128:
            errors.append("Article title exceeds maximum length of 128 characters.")

        tags = payload.metadata.get("tags", []) if payload.metadata else []
        if len(tags) > 4:
            errors.append("Dev.to allows a maximum of 4 tags.")

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            ok=len(errors) == 0,
            violations=errors,
        )

    def _get_headers(self, connection: Dict[str, Any]) -> Dict[str, str]:
        api_key = connection.get("api_key") or connection.get("token") or connection.get("access_token")
        if not api_key:
            raise ConnectorException(
                "Missing Dev.to API key in connection.",
                status_code=401,
                error_code=CANONICAL_CONNECTION_AUTH_EXPIRED,
                canonical_code=CANONICAL_CONNECTION_AUTH_EXPIRED,
            )
        return {
            "api-key": str(api_key),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _get_base_url(self, destination: Dict[str, Any]) -> str:
        base_url = destination.get("base_url") or destination.get("instance_url") or self.DEFAULT_BASE_URL
        return str(base_url).rstrip("/")

    async def publish(
        self,
        payload: ContentPayload,
        destination: Dict[str, Any],
        connection: Dict[str, Any],
        idempotency_key: Optional[str] = None,
    ) -> PublishResult:
        # Check simulation mode
        if connection.get("simulation") or destination.get("simulation"):
            sim_id = f"sim_devto_{idempotency_key or 'post'}"
            return PublishResult(
                platform_post_id=sim_id,
                url=f"https://dev.to/simulated/{sim_id}",
                status="published",
                metadata={"simulation": True, "connector": "devto"},
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
        headers = self._get_headers(connection)

        tags = payload.metadata.get("tags", []) if payload.metadata else []
        published_flag = destination.get("published", True)
        series = payload.metadata.get("series") if payload.metadata else None

        article_data: Dict[str, Any] = {
            "title": payload.title or payload.text[:60].strip(),
            "body_markdown": payload.text,
            "published": published_flag,
            "tags": tags[:4],
        }
        if series:
            article_data["series"] = series

        url = f"{base_url}/articles"

        async with httpx.AsyncClient(timeout=20.0) as client:
            try:
                resp = await client.post(url, json={"article": article_data}, headers=headers)
            except httpx.RequestError as exc:
                raise ConnectorException(
                    f"Dev.to network error: {str(exc)}",
                    status_code=503,
                    error_code="PLATFORM_UNAVAILABLE",
                    retryable=True,
                )

        if resp.status_code == 401 or resp.status_code == 403:
            raise ConnectorException(
                "Dev.to authentication failed or invalid API key.",
                status_code=401,
                error_code=CANONICAL_CONNECTION_AUTH_EXPIRED,
                canonical_code=CANONICAL_CONNECTION_AUTH_EXPIRED,
            )
        elif resp.status_code == 422:
            raise ConnectorException(
                f"Dev.to rejected content: {resp.text}",
                status_code=422,
                error_code=CANONICAL_PLATFORM_CONTENT_REJECTED,
                canonical_code=CANONICAL_PLATFORM_CONTENT_REJECTED,
            )
        elif resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After", "60")
            raise ConnectorException(
                "Dev.to rate limit exceeded.",
                status_code=429,
                error_code=CANONICAL_PLATFORM_RATE_LIMIT,
                canonical_code=CANONICAL_PLATFORM_RATE_LIMIT,
                retryable=True,
                details={"retry_after": retry_after},
            )
        elif resp.status_code not in (200, 201):
            raise ConnectorException(
                f"Dev.to publish failed with status {resp.status_code}: {resp.text}",
                status_code=resp.status_code,
                error_code="PLATFORM_ERROR",
            )

        data = resp.json()
        post_id = str(data.get("id"))
        post_url = data.get("url") or f"https://dev.to/article/{post_id}"

        return PublishResult(
            platform_post_id=post_id,
            url=post_url,
            status="published" if published_flag else "draft",
            metadata={"devto_id": post_id, "slug": data.get("slug")},
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
                "live_url": f"https://dev.to/simulated/{platform_post_id}",
                "platform_post_id": platform_post_id,
                "simulation": True,
            }

        base_url = self._get_base_url(destination)
        headers = self._get_headers(connection)
        url = f"{base_url}/articles/{platform_post_id}"

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.get(url, headers=headers)
            except httpx.RequestError as exc:
                raise ConnectorException(
                    f"Dev.to network error: {str(exc)}",
                    status_code=503,
                    error_code="PLATFORM_UNAVAILABLE",
                    retryable=True,
                )

        if resp.status_code == 404:
            return {"status": "not_found", "platform_post_id": platform_post_id}
        elif resp.status_code != 200:
            raise ConnectorException(
                f"Dev.to get_status failed: {resp.text}",
                status_code=resp.status_code,
                error_code="PLATFORM_ERROR",
            )

        data = resp.json()
        return {
            "status": "published" if data.get("published", True) else "draft",
            "live_url": data.get("url"),
            "platform_post_id": str(data.get("id")),
            "title": data.get("title"),
            "readable_publish_date": data.get("readable_publish_date"),
        }

    async def delete(
        self,
        platform_post_id: str,
        destination: Dict[str, Any],
        connection: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Dev.to REST API does not offer a permanent DELETE endpoint in public API v1.
        Instead, the standard capability response is unpublishing the article (PUT /articles/{id} with published: false)
        or returning an honest capability-aware response if unpublishing fails.
        """
        if connection.get("simulation") or destination.get("simulation") or platform_post_id.startswith("sim_"):
            return {"deleted": True, "platform_post_id": platform_post_id, "simulation": True}

        base_url = self._get_base_url(destination)
        headers = self._get_headers(connection)
        url = f"{base_url}/articles/{platform_post_id}"

        # Unpublish article as the safest deletion alternative on Dev.to
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.put(url, json={"article": {"published": False}}, headers=headers)
            except httpx.RequestError as exc:
                raise ConnectorException(
                    f"Dev.to network error during unpublish: {str(exc)}",
                    status_code=503,
                    error_code="PLATFORM_UNAVAILABLE",
                    retryable=True,
                )

        if resp.status_code in (200, 204):
            return {
                "deleted": True,
                "platform_post_id": platform_post_id,
                "strategy": "unpublished",
                "note": "Dev.to article unpublished as hard-delete is restricted by Forem API v1.",
            }
        elif resp.status_code == 404:
            return {"deleted": True, "platform_post_id": platform_post_id, "note": "Article not found."}
        else:
            raise ConnectorException(
                f"Dev.to unpublish failed: {resp.text}",
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
                "views": 42,
                "reactions": 10,
                "comments": 2,
                "shares": 0,
                "simulation": True,
            }

        base_url = self._get_base_url(destination)
        headers = self._get_headers(connection)
        url = f"{base_url}/articles/{platform_post_id}"

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=headers)

        if resp.status_code == 200:
            data = resp.json()
            return {
                "platform_post_id": platform_post_id,
                "views": data.get("page_views_count", 0),
                "reactions": data.get("public_reactions_count", 0),
                "comments": data.get("comments_count", 0),
                "shares": 0,
            }
        return {"platform_post_id": platform_post_id, "views": 0, "reactions": 0, "comments": 0}
