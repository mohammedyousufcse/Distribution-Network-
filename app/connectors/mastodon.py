"""Real Mastodon destination connector implementing the BaseConnector interface."""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import httpx
from app.config import get_settings
from app.connectors.base import BaseConnector
from app.logging import get_logger
from app.models.errors import (
    AuthExpiredError,
    ContentRejectedError,
    DestinationError,
    DestinationSpecViolationError,
    ForbiddenError,
    NetworkError,
    RateLimitedError,
)

logger = get_logger("app.connectors.mastodon")

# Maximum allowed post character count on standard Mastodon instances
MASTODON_MAX_LENGTH = 500


class MastodonConnector(BaseConnector):
    """Real Mastodon connector integrating with the official Mastodon REST API."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        access_token: Optional[str] = None,
        http_client: Optional[httpx.Client] = None,
        timeout: float = 10.0,
        allow_insecure_http: bool = False,
    ) -> None:
        """Initialize Mastodon connector.

        Args:
            base_url: Optional explicit instance base URL (e.g. 'https://mastodon.social').
            access_token: Optional explicit OAuth bearer access token.
            http_client: Optional injected httpx.Client for testing or transport override.
            timeout: Default request timeout in seconds.
            allow_insecure_http: If True, allow http:// for non-local addresses.
        """
        self._explicit_base_url = base_url
        self._explicit_access_token = access_token
        self._client = http_client
        self.timeout = timeout
        self.allow_insecure_http = allow_insecure_http

    def get_manifest(self) -> Dict[str, Any]:
        """Return manifest for the Mastodon destination connector."""
        return {
            "key": "mastodon",
            "version": "1.0.0",
            "tier": "core",
            "auth": "bearer",
            "surfaces": ["status"],
            "content_types": ["text/plain"],
            "specification_limits": {
                "max_text_length": MASTODON_MAX_LENGTH,
                "min_text_length": 1,
            },
            "rate_limits": {
                "requests_per_minute": 10,
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
                "401": "CONNECTION_AUTH_EXPIRED",
                "403": "PLATFORM_CONTENT_REJECTED",
                "429": "PLATFORM_RATE_LIMIT",
                "422": "DEST_SPEC_VIOLATION",
                "500": "DESTINATION_ERROR",
            },
            "instance_parameter": "base_url",
        }

    def _get_effective_config(self) -> tuple[str, str]:
        """Resolve and validate base URL and access token.

        Returns:
            Tuple of (clean_base_url, access_token).

        Raises:
            DestinationSpecViolationError: If base URL is missing, invalid, or non-HTTPS.
            AuthExpiredError: If access token is missing or empty.
        """
        settings = get_settings()
        raw_url = (
            self._explicit_base_url
            if self._explicit_base_url is not None
            else settings.MASTODON_BASE_URL
        )
        raw_token = (
            self._explicit_access_token
            if self._explicit_access_token is not None
            else settings.MASTODON_ACCESS_TOKEN
        )

        if not raw_url or not str(raw_url).strip():
            raise DestinationSpecViolationError(
                "Mastodon base URL is missing or not configured. Please set MASTODON_BASE_URL."
            )

        clean_url = str(raw_url).strip().rstrip("/")
        if not clean_url.startswith("https://"):
            # Allow non-https only for localhost / test addresses or if explicitly permitted
            is_local = (
                clean_url.startswith("http://localhost")
                or clean_url.startswith("http://127.0.0.1")
                or clean_url.startswith("http://testserver")
            )
            if not is_local and not self.allow_insecure_http:
                raise DestinationSpecViolationError(
                    "Mastodon instance URL must use HTTPS by default for secure communication."
                )

        if not raw_token or not str(raw_token).strip():
            raise AuthExpiredError(
                "Mastodon access token is missing or not configured. Please set MASTODON_ACCESS_TOKEN."
            )

        return clean_url, str(raw_token).strip()

    def _get_http_client(self) -> httpx.Client:
        """Return the injected HTTP client or create a new scoped one."""
        if self._client is not None:
            return self._client
        return httpx.Client(timeout=self.timeout)

    def validate(self, content: Dict[str, Any]) -> Dict[str, Any]:
        """Validate content payload against Mastodon destination constraints.

        Args:
            content: Content dictionary to evaluate.

        Returns:
            Dict containing 'valid': True or 'valid': False with an 'error' message.
        """
        if not isinstance(content, dict):
            return {
                "valid": False,
                "error": "Content must be a dictionary.",
            }

        text = content.get("text")
        if not isinstance(text, str) or not text.strip():
            return {
                "valid": False,
                "error": "Content must contain a non-empty 'text' field.",
            }

        if len(text) > MASTODON_MAX_LENGTH:
            return {
                "valid": False,
                "error": (
                    f"Content length of {len(text)} exceeds maximum allowed "
                    f"limit of {MASTODON_MAX_LENGTH} characters for Mastodon."
                ),
            }

        return {
            "valid": True,
        }

    def publish(self, content: Dict[str, Any]) -> Dict[str, Any]:
        """Publish status to Mastodon via POST /api/v1/statuses.

        Args:
            content: Content dictionary containing status text and optional metadata.

        Returns:
            Dict containing publication status, remote post ID, public URL, and metadata.
        """
        validation = self.validate(content)
        if not validation["valid"]:
            return {
                "success": False,
                "error": validation["error"],
            }

        base_url, token = self._get_effective_config()
        endpoint = f"{base_url}/api/v1/statuses"

        payload: Dict[str, Any] = {
            "status": str(content["text"]).strip(),
        }

        # Optional Mastodon status fields
        for field in ("visibility", "spoiler_text", "sensitive", "language", "in_reply_to_id"):
            if field in content and content[field] is not None:
                payload[field] = content[field]

        if "media_ids" in content and isinstance(content["media_ids"], list):
            payload["media_ids"] = content["media_ids"]

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        # Forward idempotency key downstream if specified
        if "idempotency_key" in content and content["idempotency_key"]:
            headers["Idempotency-Key"] = str(content["idempotency_key"]).strip()

        client = self._get_http_client()
        should_close = self._client is None

        try:
            response = client.post(endpoint, json=payload, headers=headers)
            if response.status_code in (200, 201):
                try:
                    data = response.json()
                except Exception as exc:
                    raise DestinationError("Mastodon returned a malformed non-JSON response.") from exc

                if not isinstance(data, dict) or "id" not in data:
                    raise DestinationError("Mastodon returned an unexpected payload missing post identifier.")

                post_id = str(data["id"])
                # Extract public URL; fall back to canonical uri or construct profile URL
                public_url = (
                    data.get("url")
                    or data.get("uri")
                    or f"{base_url}/@{data.get('account', {}).get('username', 'user')}/{post_id}"
                )

                created_at = data.get("created_at") or datetime.now(timezone.utc).isoformat()

                return {
                    "success": True,
                    "id": post_id,
                    "status": "published",
                    "destination": "mastodon",
                    "url": public_url,
                    "message": "Content successfully published to Mastodon.",
                    "created_at": created_at,
                }

            self._handle_error_response(response)
        except (
            AuthExpiredError,
            RateLimitedError,
            ContentRejectedError,
            ForbiddenError,
            DestinationSpecViolationError,
            DestinationError,
            NetworkError,
        ):
            raise
        except httpx.TimeoutException as exc:
            raise NetworkError(f"Request to Mastodon timed out: {exc}") from exc
        except httpx.RequestError as exc:
            raise NetworkError(f"Network error contacting Mastodon: {exc}") from exc
        except Exception as exc:
            raise DestinationError(f"Unexpected error communicating with Mastodon: {exc}") from exc
        finally:
            if should_close:
                client.close()

    def get_status(self, post_id: str) -> Dict[str, Any]:
        """Retrieve status details from Mastodon via GET /api/v1/statuses/{id}.

        Args:
            post_id: The remote Mastodon status identifier.

        Returns:
            Dict containing post metadata if found, or not-found status if missing.
        """
        clean_id = str(post_id).strip()
        if not clean_id:
            return {
                "found": False,
                "id": post_id,
                "error": "Post ID cannot be empty.",
            }

        base_url, token = self._get_effective_config()
        endpoint = f"{base_url}/api/v1/statuses/{clean_id}"

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

        client = self._get_http_client()
        should_close = self._client is None

        try:
            response = client.get(endpoint, headers=headers)
            if response.status_code == 200:
                try:
                    data = response.json()
                except Exception as exc:
                    raise DestinationError("Mastodon returned a malformed non-JSON response.") from exc

                if not isinstance(data, dict) or "id" not in data:
                    raise DestinationError("Mastodon returned an unexpected status payload missing ID.")

                return {
                    "found": True,
                    "id": str(data["id"]),
                    "status": "published",
                    "destination": "mastodon",
                    "url": data.get("url") or data.get("uri"),
                    "content": data.get("content") or data.get("text"),
                    "created_at": data.get("created_at"),
                }

            if response.status_code == 404:
                return {
                    "found": False,
                    "id": clean_id,
                    "error": f"Post '{clean_id}' not found on Mastodon.",
                }

            self._handle_error_response(response)
        except (
            AuthExpiredError,
            RateLimitedError,
            ContentRejectedError,
            ForbiddenError,
            DestinationSpecViolationError,
            DestinationError,
            NetworkError,
        ):
            raise
        except httpx.TimeoutException as exc:
            raise NetworkError(f"Request to Mastodon timed out: {exc}") from exc
        except httpx.RequestError as exc:
            raise NetworkError(f"Network error contacting Mastodon: {exc}") from exc
        finally:
            if should_close:
                client.close()

    def delete(self, post_id: str) -> Dict[str, Any]:
        """Delete status from Mastodon via DELETE /api/v1/statuses/{id}.

        Args:
            post_id: The remote Mastodon status identifier.

        Returns:
            Dict containing deletion outcome or not-found status if missing.
        """
        clean_id = str(post_id).strip()
        if not clean_id:
            return {
                "success": False,
                "id": post_id,
                "error": "Post ID cannot be empty.",
            }

        base_url, token = self._get_effective_config()
        endpoint = f"{base_url}/api/v1/statuses/{clean_id}"

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

        client = self._get_http_client()
        should_close = self._client is None

        try:
            response = client.delete(endpoint, headers=headers)
            if response.status_code == 200:
                return {
                    "success": True,
                    "id": clean_id,
                    "destination": "mastodon",
                    "message": f"Post '{clean_id}' successfully deleted from Mastodon.",
                }

            if response.status_code == 404:
                return {
                    "success": False,
                    "id": clean_id,
                    "error": f"Post '{clean_id}' not found on Mastodon.",
                }

            self._handle_error_response(response)
        except (
            AuthExpiredError,
            RateLimitedError,
            ContentRejectedError,
            ForbiddenError,
            DestinationSpecViolationError,
            DestinationError,
            NetworkError,
        ):
            raise
        except httpx.TimeoutException as exc:
            raise NetworkError(f"Request to Mastodon timed out: {exc}") from exc
        except httpx.RequestError as exc:
            raise NetworkError(f"Network error contacting Mastodon: {exc}") from exc
        finally:
            if should_close:
                client.close()

    def _handle_error_response(self, response: httpx.Response) -> None:
        """Map Mastodon HTTP error status and body to project exceptions."""
        error_msg = f"HTTP {response.status_code}"
        try:
            body = response.json()
            if isinstance(body, dict):
                error_msg = body.get("error") or body.get("error_description") or str(body)
            elif isinstance(body, str):
                error_msg = body
        except Exception:
            text = response.text
            if text:
                error_msg = text[:200]

        status_code = response.status_code

        # HTTP 401: Invalid credentials or expired access token
        if status_code == 401:
            raise AuthExpiredError(f"Mastodon authentication failed: {error_msg}")

        # HTTP 429: Downstream rate limit reached
        if status_code == 429:
            retry_after = response.headers.get("Retry-After")
            detail = f"Downstream Mastodon rate limit reached: {error_msg}."
            if retry_after:
                detail += f" Retry after {retry_after} seconds."
            raise RateLimitedError(detail)

        # HTTP 403: Forbidden (distinguish content rejection from permission errors)
        if status_code == 403:
            lower = error_msg.lower()
            moderation_keywords = ("content", "moderation", "rejected", "blocked", "filter", "rule", "forbidden content")
            if any(k in lower for k in moderation_keywords):
                raise ContentRejectedError(f"Mastodon rejected content: {error_msg}")
            raise ForbiddenError(f"Mastodon permission denied or action forbidden: {error_msg}")

        # HTTP 422: Destination specification or validation error
        if status_code == 422:
            raise DestinationSpecViolationError(f"Mastodon rejected status content: {error_msg}")

        # Server error (5xx)
        if 500 <= status_code <= 599:
            raise DestinationError(f"Mastodon server error ({status_code}): {error_msg}")

        # Other unexpected responses
        raise DestinationError(f"Mastodon returned unexpected status {status_code}: {error_msg}")
