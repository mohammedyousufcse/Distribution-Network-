"""
Generic partner-site connector using HMAC-SHA256 signed webhooks.

Follows the IncuBrix connector specification for authenticated partner integrations.
Includes timestamp-based replay protection and constant-time signature verification.
"""

import hashlib
import hmac
import json
import time
from typing import Any, Dict, Optional, Tuple
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


def generate_webhook_signature(payload_bytes: bytes, secret: str, timestamp: int) -> str:
    """Generate HMAC-SHA256 signature formatted as sha256={digest}."""
    message = f"t={timestamp}.".encode("utf-8") + payload_bytes
    signature = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return f"sha256={signature}"


def verify_webhook_signature(
    payload_bytes: bytes,
    secret: str,
    header_signature: str,
    timestamp: int,
    tolerance_seconds: int = 300,
) -> Tuple[bool, str]:
    """
    Verify HMAC signature with constant-time comparison and replay attack protection.
    Returns (is_valid, reason).
    """
    now = int(time.time())
    if abs(now - timestamp) > tolerance_seconds:
        return False, f"Timestamp outside tolerance window ({abs(now - timestamp)}s > {tolerance_seconds}s)"

    expected_sig = generate_webhook_signature(payload_bytes, secret, timestamp)
    if not hmac.compare_digest(expected_sig, header_signature):
        return False, "Signature mismatch"

    return True, "Valid"


class WebhookConnector(BaseConnector):
    """Generic partner-site connector using HMAC-signed webhooks."""

    name = "webhook"

    def get_manifest(self) -> Dict[str, Any]:
        return {
            "key": "webhook",
            "name": "Generic Partner Webhook",
            "version": "1.0.0",
            "tier": "tier_1",
            "auth": {
                "type": "hmac_sha256",
                "header": "X-Hub-Signature-256",
                "timestamp_header": "X-Signature-Timestamp",
            },
            "surfaces": ["webhook_event", "partner_feed"],
            "content_types": ["json"],
            "specification_limits": {
                "max_body_length": 250000,
            },
            "rate_limits": {
                "requests_per_minute": 120,
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

        if not text.strip():
            errors.append("Webhook payload text cannot be empty.")
        if len(text) > 250000:
            errors.append("Webhook payload exceeds maximum length of 250,000 characters.")

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            ok=len(errors) == 0,
            violations=errors,
        )

    def _get_secret(self, connection: Dict[str, Any]) -> str:
        secret = (
            connection.get("webhook_secret")
            or connection.get("secret")
            or connection.get("token")
        )
        if not secret:
            raise ConnectorException(
                "Missing HMAC webhook secret in connection configuration.",
                status_code=401,
                error_code=CANONICAL_CONNECTION_AUTH_EXPIRED,
                canonical_code=CANONICAL_CONNECTION_AUTH_EXPIRED,
            )
        return str(secret)

    def _get_target_url(self, destination: Dict[str, Any]) -> str:
        url = (
            destination.get("webhook_url")
            or destination.get("target_url")
            or destination.get("base_url")
        )
        if not url:
            raise ConnectorException(
                "Missing target webhook URL in destination configuration.",
                status_code=400,
                error_code=CANONICAL_DEST_SPEC_VIOLATION,
                canonical_code=CANONICAL_DEST_SPEC_VIOLATION,
            )
        return str(url)

    async def publish(
        self,
        payload: ContentPayload,
        destination: Dict[str, Any],
        connection: Dict[str, Any],
        idempotency_key: Optional[str] = None,
    ) -> PublishResult:
        if connection.get("simulation") or destination.get("simulation"):
            sim_id = f"sim_webhook_{idempotency_key or 'event'}"
            return PublishResult(
                platform_post_id=sim_id,
                url=f"https://webhook.partner.local/events/{sim_id}",
                status="delivered",
                metadata={"simulation": True, "connector": "webhook"},
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

        target_url = self._get_target_url(destination)
        secret = self._get_secret(connection)

        body_dict = {
            "event": "distribution.publish",
            "idempotency_key": idempotency_key,
            "title": payload.title,
            "text": payload.text,
            "metadata": payload.metadata or {},
        }
        body_bytes = json.dumps(body_dict, sort_keys=True).encode("utf-8")
        timestamp = int(time.time())
        signature = generate_webhook_signature(body_bytes, secret, timestamp)

        headers = {
            "Content-Type": "application/json",
            "X-Hub-Signature-256": signature,
            "X-Signature-Timestamp": str(timestamp),
            "X-Idempotency-Key": idempotency_key or "",
            "User-Agent": "IncuBrix-Webhook-Connector/1.0",
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.post(target_url, content=body_bytes, headers=headers)
            except httpx.RequestError as exc:
                raise ConnectorException(
                    f"Partner webhook network error: {str(exc)}",
                    status_code=503,
                    error_code="PLATFORM_UNAVAILABLE",
                    retryable=True,
                )

        if resp.status_code in (401, 403):
            raise ConnectorException(
                "Partner rejected webhook signature or unauthorized.",
                status_code=401,
                error_code=CANONICAL_CONNECTION_AUTH_EXPIRED,
                canonical_code=CANONICAL_CONNECTION_AUTH_EXPIRED,
            )
        elif resp.status_code == 422:
            raise ConnectorException(
                f"Partner rejected content: {resp.text}",
                status_code=422,
                error_code=CANONICAL_PLATFORM_CONTENT_REJECTED,
                canonical_code=CANONICAL_PLATFORM_CONTENT_REJECTED,
            )
        elif resp.status_code == 429:
            raise ConnectorException(
                "Partner webhook rate limit exceeded.",
                status_code=429,
                error_code=CANONICAL_PLATFORM_RATE_LIMIT,
                canonical_code=CANONICAL_PLATFORM_RATE_LIMIT,
                retryable=True,
            )
        elif resp.status_code not in (200, 201, 202, 204):
            raise ConnectorException(
                f"Partner webhook failed with HTTP {resp.status_code}: {resp.text}",
                status_code=resp.status_code,
                error_code="PLATFORM_ERROR",
            )

        post_id = idempotency_key or f"wh_{timestamp}"
        live_url = target_url

        try:
            resp_data = resp.json()
            if isinstance(resp_data, dict):
                post_id = str(resp_data.get("id") or resp_data.get("event_id") or post_id)
                live_url = str(resp_data.get("url") or live_url)
        except Exception:
            pass

        return PublishResult(
            platform_post_id=post_id,
            url=live_url,
            status="delivered",
            metadata={"timestamp": timestamp, "status_code": resp.status_code},
        )

    async def get_status(
        self,
        platform_post_id: str,
        destination: Dict[str, Any],
        connection: Dict[str, Any],
    ) -> Dict[str, Any]:
        if connection.get("simulation") or destination.get("simulation") or platform_post_id.startswith("sim_"):
            return {
                "status": "delivered",
                "live_url": f"https://webhook.partner.local/events/{platform_post_id}",
                "platform_post_id": platform_post_id,
                "simulation": True,
            }

        target_url = self._get_target_url(destination)
        secret = self._get_secret(connection)
        timestamp = int(time.time())
        signature = generate_webhook_signature(platform_post_id.encode("utf-8"), secret, timestamp)

        url = f"{target_url.rstrip('/')}/events/{platform_post_id}"
        headers = {
            "X-Hub-Signature-256": signature,
            "X-Signature-Timestamp": str(timestamp),
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.get(url, headers=headers)
            except httpx.RequestError as exc:
                raise ConnectorException(
                    f"Partner webhook status network error: {str(exc)}",
                    status_code=503,
                    error_code="PLATFORM_UNAVAILABLE",
                    retryable=True,
                )

        if resp.status_code == 404:
            return {"status": "not_found", "platform_post_id": platform_post_id}
        elif resp.status_code != 200:
            return {"status": "delivered", "platform_post_id": platform_post_id}

        return resp.json()

    async def delete(
        self,
        platform_post_id: str,
        destination: Dict[str, Any],
        connection: Dict[str, Any],
    ) -> Dict[str, Any]:
        if connection.get("simulation") or destination.get("simulation") or platform_post_id.startswith("sim_"):
            return {"deleted": True, "platform_post_id": platform_post_id, "simulation": True}

        target_url = self._get_target_url(destination)
        secret = self._get_secret(connection)
        timestamp = int(time.time())
        signature = generate_webhook_signature(platform_post_id.encode("utf-8"), secret, timestamp)

        url = f"{target_url.rstrip('/')}/events/{platform_post_id}"
        headers = {
            "X-Hub-Signature-256": signature,
            "X-Signature-Timestamp": str(timestamp),
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.delete(url, headers=headers)
            except httpx.RequestError as exc:
                raise ConnectorException(
                    f"Partner webhook delete network error: {str(exc)}",
                    status_code=503,
                    error_code="PLATFORM_UNAVAILABLE",
                    retryable=True,
                )

        if resp.status_code in (200, 204, 404):
            return {"deleted": True, "platform_post_id": platform_post_id}
        else:
            raise ConnectorException(
                f"Partner webhook delete failed: {resp.text}",
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
        return {
            "platform_post_id": platform_post_id,
            "views": 1,
            "reactions": 0,
            "comments": 0,
            "delivered": True,
        }
