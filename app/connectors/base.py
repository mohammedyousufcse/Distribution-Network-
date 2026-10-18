"""Base connector interface for destination integrations."""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class BaseConnector(ABC):
    """Abstract base class that all destination connectors must implement."""

    @abstractmethod
    def validate(self, content: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        """Validate content payload prior to publishing.

        Args:
            content: Dictionary containing content fields (e.g., text, tags).
            **kwargs: Optional destination or connection configurations.

        Returns:
            Dict containing validation status and error messages if invalid.
        """
        pass

    @abstractmethod
    def publish(self, content: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        """Publish content to the destination platform.

        Args:
            content: Dictionary containing the payload to publish.
            **kwargs: Optional destination, connection, or idempotency parameters.

        Returns:
            Dict containing publication status, post ID, and metadata.
        """
        pass

    @abstractmethod
    def get_status(self, post_id: str, **kwargs: Any) -> Dict[str, Any]:
        """Retrieve the current status of a published post.

        Args:
            post_id: The unique post identifier.
            **kwargs: Optional connection configuration.

        Returns:
            Dict containing the current status or error details.
        """
        pass

    @abstractmethod
    def delete(self, post_id: str, **kwargs: Any) -> Dict[str, Any]:
        """Delete or unpublish a post by its identifier.

        Args:
            post_id: The unique post identifier to remove.
            **kwargs: Optional connection configuration.

        Returns:
            Dict indicating whether the deletion succeeded or failed.
        """
        pass

    def get_manifest(self) -> Dict[str, Any]:
        """Return connector manifest describing metadata, capabilities, and limits."""
        return {
            "key": getattr(self, "connector_key", self.__class__.__name__.lower().replace("connector", "")),
            "version": "1.0.0",
            "tier": "core",
            "auth": "none",
            "surfaces": ["post"],
            "content_types": ["text/plain"],
            "specification_limits": {"max_text_length": 280},
            "rate_limits": {"requests_per_minute": 5},
            "capabilities": {
                "validate": True,
                "publish": True,
                "get_status": True,
                "delete": True,
                "fetch_metrics": False,
                "refresh_auth": False,
                "build_assist_pack": False,
            },
            "error_map": {},
            "instance_parameter": "base_url",
        }

    def fetch_metrics(self, post_id: str, connection: Optional[Dict[str, Any]] = None, since: Optional[str] = None) -> Dict[str, Any]:
        """Fetch normalized metrics for a published post (optional capability)."""
        return {
            "supported": False,
            "post_id": post_id,
            "message": f"Metrics retrieval not supported by {self.__class__.__name__}.",
        }

    def refresh_auth(self, connection: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Refresh expired authentication credentials (optional capability)."""
        return {
            "supported": False,
            "message": f"Auth token refresh not supported by {self.__class__.__name__}.",
        }

    def build_assist_pack(self, content: Dict[str, Any], destination: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Build ready-to-post manual assist package (optional capability)."""
        return {
            "supported": False,
            "message": f"Assist pack generation not supported by {self.__class__.__name__}.",
        }

