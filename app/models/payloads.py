"""
Data models for content payloads and operation results.

Appendix A contract schemas for rendition and publication results.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ContentPayload(BaseModel):
    """Normalized content payload (Appendix A rendition)."""

    text: str = Field(description="Body text content or article body.")
    title: Optional[str] = Field(default=None, description="Optional post or article title.")
    media_urls: Optional[List[str]] = Field(default=None, description="Optional media or attachment URLs.")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Platform or destination metadata.")

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)

    def get(self, item: str, default: Any = None) -> Any:
        return getattr(self, item, default)

    model_config = {
        "extra": "allow",
        "populate_by_name": True,
    }


class PublishResult(BaseModel):
    """Normalized publication result."""

    platform_post_id: str = Field(description="Platform-assigned post identifier.")
    url: str = Field(description="Live platform URL or deep link.")
    status: str = Field(default="published", description="Publication status.")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Diagnostic and platform metadata.")

    @property
    def id(self) -> str:
        """Alias for platform_post_id for backward compatibility."""
        return self.platform_post_id

    @property
    def live_url(self) -> str:
        """Alias for url for Appendix A compliance."""
        return self.url

    def __getitem__(self, item: str) -> Any:
        if item == "id":
            return self.platform_post_id
        if item == "live_url":
            return self.url
        return getattr(self, item)

    def get(self, item: str, default: Any = None) -> Any:
        try:
            return self[item]
        except AttributeError:
            return default

    model_config = {
        "extra": "allow",
        "populate_by_name": True,
    }
