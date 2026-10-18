"""Safe mock connector for simulating publishing locally in memory."""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from app.connectors.base import BaseConnector


class MockConnector(BaseConnector):
    """In-memory mock connector simulating destination publishing without network calls."""

    def __init__(self) -> None:
        """Initialize in-memory storage for published mock posts."""
        self._posts: Dict[str, Dict[str, Any]] = {}
        self._simulated_error: Optional[str] = None

    def set_simulated_error(self, error_code: Optional[str]) -> None:
        """Set a simulated error for testing error pipelines without real external dependencies.

        Supported values:
            'AUTH_EXPIRED', 'RATE_LIMITED', 'QUOTA_EXHAUSTED', 'CONTENT_REJECTED', or None.
        """
        self._simulated_error = error_code

    def clear(self) -> None:
        """Clear all stored mock posts and reset any simulated error flags."""
        self._posts.clear()
        self._simulated_error = None

    def get_manifest(self) -> Dict[str, Any]:
        """Return manifest for the Mock destination connector."""
        return {
            "key": "mock",
            "version": "1.0.0",
            "tier": "mock",
            "auth": "none",
            "surfaces": ["in_memory_post"],
            "content_types": ["text/plain"],
            "specification_limits": {
                "max_text_length": 280,
                "min_text_length": 1,
            },
            "rate_limits": {
                "requests_per_minute": 5,
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
                "AUTH_EXPIRED": "CONNECTION_AUTH_EXPIRED",
                "RATE_LIMITED": "PLATFORM_RATE_LIMIT",
                "QUOTA_EXHAUSTED": "PLATFORM_QUOTA_EXHAUSTED",
                "CONTENT_REJECTED": "PLATFORM_CONTENT_REJECTED",
            },
            "instance_parameter": None,
        }



    def validate(self, content: Dict[str, Any]) -> Dict[str, Any]:
        """Validate that content is a dictionary with a non-empty text field.

        Args:
            content: Content dictionary to validate.

        Returns:
            Dict with 'valid': True or 'valid': False and an 'error' message.
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

        return {
            "valid": True,
        }

    def publish(self, content: Dict[str, Any]) -> Dict[str, Any]:
        """Simulate publishing locally without contacting external websites.

        Args:
            content: Content dictionary to publish.

        Returns:
            Dict containing post ID, publication status, and mock destination marker.
        """
        # Check for simulated error condition (for controlled testing of error handling)
        simulated = content.get("simulate_error") or self._simulated_error
        if simulated:
            from app.models.errors import (
                AuthExpiredError,
                ContentRejectedError,
                QuotaExhaustedError,
                RateLimitedError,
            )

            if simulated == "AUTH_EXPIRED":
                raise AuthExpiredError("Simulated error: Mock destination authentication token has expired.")
            elif simulated == "RATE_LIMITED":
                raise RateLimitedError("Simulated error: Mock destination rate limit reached.")
            elif simulated == "QUOTA_EXHAUSTED":
                raise QuotaExhaustedError("Simulated error: Mock destination post quota has been exhausted.")
            elif simulated == "CONTENT_REJECTED":
                raise ContentRejectedError("Simulated error: Mock destination moderation rejected this content.")

        validation = self.validate(content)
        if not validation["valid"]:
            return {
                "success": False,
                "error": validation["error"],
            }


        post_id = f"mock_{uuid.uuid4().hex[:12]}"
        timestamp = datetime.now(timezone.utc).isoformat()

        post_record = {
            "id": post_id,
            "content": content,
            "status": "published",
            "destination": "mock",
            "created_at": timestamp,
        }

        self._posts[post_id] = post_record

        return {
            "success": True,
            "id": post_id,
            "status": "published",
            "destination": "mock",
            "message": "Content successfully simulated in local mock store.",
            "created_at": timestamp,
        }

    def get_status(self, post_id: str) -> Dict[str, Any]:
        """Check the status of a previously published mock post.

        Args:
            post_id: The unique post identifier.

        Returns:
            Dict with post status if found, or not-found error if missing.
        """
        if post_id not in self._posts:
            return {
                "found": False,
                "id": post_id,
                "error": f"Post '{post_id}' not found.",
            }

        post = self._posts[post_id]
        return {
            "found": True,
            "id": post_id,
            "status": post["status"],
            "destination": post["destination"],
            "content": post["content"],
            "created_at": post["created_at"],
        }

    def delete(self, post_id: str) -> Dict[str, Any]:
        """Delete an existing mock post by ID.

        Args:
            post_id: The unique post identifier to remove.

        Returns:
            Dict indicating deletion success or not-found error.
        """
        if post_id not in self._posts:
            return {
                "success": False,
                "id": post_id,
                "error": f"Post '{post_id}' not found.",
            }

        del self._posts[post_id]
        return {
            "success": True,
            "id": post_id,
            "message": f"Post '{post_id}' successfully deleted.",
        }
