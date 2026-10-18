"""Destination policy and validation models."""

from typing import Any, Optional
from pydantic import BaseModel, Field

# Stable error codes for policy and validation failures
DEST_SPEC_VIOLATION = "DEST_SPEC_VIOLATION"
DEST_RULE_FREQUENCY_CAP = "DEST_RULE_FREQUENCY_CAP"
ERROR_CODE_SPEC_VIOLATION = "DESTINATION_SPEC_VIOLATION"
ERROR_CODE_FREQUENCY_CAP = "FREQUENCY_CAP_EXCEEDED"


class DestinationPolicy(BaseModel):
    """Configuration rules and constraints for publishing to a destination."""

    destination_key: str = Field(
        default="mock",
        description="Unique identifier of the destination platform.",
    )
    max_text_length: int = Field(
        default=280,
        ge=1,
        description="Maximum allowed character count for the text field.",
    )
    min_text_length: int = Field(
        default=1,
        ge=0,
        description="Minimum required character count for the text field.",
    )
    max_requests_per_window: int = Field(
        default=5,
        ge=1,
        description="Maximum number of publish operations allowed within the time window.",
    )
    window_seconds: int = Field(
        default=60,
        ge=1,
        description="Duration of the frequency cap window in seconds.",
    )
    weekly_frequency_cap: Optional[int] = Field(
        default=None,
        description="Maximum number of publish operations allowed within a 7-day rolling window.",
    )
    allow_self_promotion: bool = Field(
        default=True,
        description="Whether commercial or self-promotional content is permitted.",
    )
    allow_links: bool = Field(
        default=True,
        description="Whether external hyperlinks are permitted in the content text.",
    )
    require_ai_disclosure: bool = Field(
        default=False,
        description="Whether content must explicitly disclose AI generation.",
    )


class PolicyValidationResult(BaseModel):
    """Result of content validation against destination policy supporting Appendix A contract."""

    valid: bool
    ok: Optional[bool] = None
    error_code: Optional[str] = None
    shared_error_code: Optional[str] = None
    error: Optional[str] = None
    errors: list = Field(default_factory=list)
    violations: list = Field(default_factory=list)

    def model_post_init(self, __context) -> None:
        if self.ok is None:
            self.ok = self.valid
        if not self.violations and self.error:
            self.violations = [self.error]
        if not self.errors and self.violations:
            self.errors = list(self.violations)

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)

    def get(self, item: str, default: Any = None) -> Any:
        return getattr(self, item, default)


# Backward-compatible alias
ValidationResult = PolicyValidationResult

