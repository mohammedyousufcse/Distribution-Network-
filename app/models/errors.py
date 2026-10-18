"""Structured error codes, models, and exceptions for destination connectors."""

from typing import Any, Dict, Optional
from fastapi import status
from pydantic import BaseModel, Field

# Canonical shared error codes from Assessment Brief Appendix A
DEST_SPEC_VIOLATION = "DEST_SPEC_VIOLATION"
DEST_RULE_FREQUENCY_CAP = "DEST_RULE_FREQUENCY_CAP"
CONNECTION_AUTH_EXPIRED = "CONNECTION_AUTH_EXPIRED"
PLATFORM_RATE_LIMIT = "PLATFORM_RATE_LIMIT"
PLATFORM_QUOTA_EXHAUSTED = "PLATFORM_QUOTA_EXHAUSTED"
PLATFORM_CONTENT_REJECTED = "PLATFORM_CONTENT_REJECTED"

# Aliases with CANONICAL_ prefix
CANONICAL_DEST_SPEC_VIOLATION = DEST_SPEC_VIOLATION
CANONICAL_DEST_RULE_FREQUENCY_CAP = DEST_RULE_FREQUENCY_CAP
CANONICAL_CONNECTION_AUTH_EXPIRED = CONNECTION_AUTH_EXPIRED
CANONICAL_PLATFORM_RATE_LIMIT = PLATFORM_RATE_LIMIT
CANONICAL_PLATFORM_QUOTA_EXHAUSTED = PLATFORM_QUOTA_EXHAUSTED
CANONICAL_PLATFORM_CONTENT_REJECTED = PLATFORM_CONTENT_REJECTED

# Legacy error code constants (for backward compatibility with existing tests)
ERROR_CODE_SPEC_VIOLATION = "DESTINATION_SPEC_VIOLATION"
ERROR_CODE_FREQUENCY_CAP = "FREQUENCY_CAP_EXCEEDED"
ERROR_CODE_AUTH_EXPIRED = "AUTH_EXPIRED"
ERROR_CODE_RATE_LIMITED = "RATE_LIMITED"
ERROR_CODE_QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
ERROR_CODE_CONTENT_REJECTED = "CONTENT_REJECTED"
ERROR_CODE_IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
ERROR_CODE_FORBIDDEN = "FORBIDDEN"
ERROR_CODE_NETWORK_ERROR = "NETWORK_ERROR"
ERROR_CODE_DESTINATION_ERROR = "DESTINATION_ERROR"

# Canonical mapping from any error code to the official shared code
CANONICAL_SHARED_ERROR_MAP: Dict[str, str] = {
    ERROR_CODE_SPEC_VIOLATION: DEST_SPEC_VIOLATION,
    ERROR_CODE_FREQUENCY_CAP: DEST_RULE_FREQUENCY_CAP,
    ERROR_CODE_AUTH_EXPIRED: CONNECTION_AUTH_EXPIRED,
    ERROR_CODE_RATE_LIMITED: PLATFORM_RATE_LIMIT,
    ERROR_CODE_QUOTA_EXHAUSTED: PLATFORM_QUOTA_EXHAUSTED,
    ERROR_CODE_CONTENT_REJECTED: PLATFORM_CONTENT_REJECTED,
    DEST_SPEC_VIOLATION: DEST_SPEC_VIOLATION,
    DEST_RULE_FREQUENCY_CAP: DEST_RULE_FREQUENCY_CAP,
    CONNECTION_AUTH_EXPIRED: CONNECTION_AUTH_EXPIRED,
    PLATFORM_RATE_LIMIT: PLATFORM_RATE_LIMIT,
    PLATFORM_QUOTA_EXHAUSTED: PLATFORM_QUOTA_EXHAUSTED,
    PLATFORM_CONTENT_REJECTED: PLATFORM_CONTENT_REJECTED,
    ERROR_CODE_IDEMPOTENCY_CONFLICT: ERROR_CODE_IDEMPOTENCY_CONFLICT,
    ERROR_CODE_FORBIDDEN: ERROR_CODE_FORBIDDEN,
    ERROR_CODE_NETWORK_ERROR: ERROR_CODE_NETWORK_ERROR,
    ERROR_CODE_DESTINATION_ERROR: ERROR_CODE_DESTINATION_ERROR,
}

# Standard HTTP status mapping for connector error codes
ERROR_STATUS_MAP: Dict[str, int] = {
    # Canonical shared codes
    DEST_SPEC_VIOLATION: status.HTTP_400_BAD_REQUEST,
    DEST_RULE_FREQUENCY_CAP: status.HTTP_429_TOO_MANY_REQUESTS,
    CONNECTION_AUTH_EXPIRED: status.HTTP_401_UNAUTHORIZED,
    PLATFORM_RATE_LIMIT: status.HTTP_429_TOO_MANY_REQUESTS,
    PLATFORM_QUOTA_EXHAUSTED: status.HTTP_429_TOO_MANY_REQUESTS,
    PLATFORM_CONTENT_REJECTED: status.HTTP_403_FORBIDDEN,

    # Legacy mappings
    ERROR_CODE_SPEC_VIOLATION: status.HTTP_400_BAD_REQUEST,
    ERROR_CODE_AUTH_EXPIRED: status.HTTP_401_UNAUTHORIZED,
    ERROR_CODE_CONTENT_REJECTED: status.HTTP_403_FORBIDDEN,
    ERROR_CODE_FORBIDDEN: status.HTTP_403_FORBIDDEN,
    ERROR_CODE_RATE_LIMITED: status.HTTP_429_TOO_MANY_REQUESTS,
    ERROR_CODE_FREQUENCY_CAP: status.HTTP_429_TOO_MANY_REQUESTS,
    ERROR_CODE_QUOTA_EXHAUSTED: status.HTTP_429_TOO_MANY_REQUESTS,
    ERROR_CODE_IDEMPOTENCY_CONFLICT: status.HTTP_409_CONFLICT,
    ERROR_CODE_NETWORK_ERROR: status.HTTP_502_BAD_GATEWAY,
    ERROR_CODE_DESTINATION_ERROR: status.HTTP_502_BAD_GATEWAY,
}


class ConnectorErrorResponse(BaseModel):
    """Consistent JSON error response model."""

    error_code: str = Field(description="Machine-readable error code.")
    shared_error_code: Optional[str] = Field(default=None, description="Standard shared error code from Appendix A.")
    code: Optional[str] = Field(default=None, description="Standard shared error code alias.")
    message: str = Field(description="Human-readable explanation of the error.")
    detail: str = Field(description="Detailed error message (matches message for compatibility).")
    error: Optional[str] = Field(default=None, description="Error description for backward compatibility.")
    violations: Optional[list] = Field(default=None, description="List of specification or rule violations.")


class ConnectorException(Exception):
    """Base exception for structured connector and policy errors."""

    def __init__(
        self,
        *args: Any,
        status_code: Optional[int] = None,
        violations: Optional[list] = None,
        error_code: Optional[str] = None,
        canonical_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        if len(args) >= 2:
            resolved_error_code = args[0]
            resolved_message = args[1]
            if len(args) >= 3 and status_code is None:
                status_code = args[2]
            if len(args) >= 4 and violations is None:
                violations = args[3]
        elif len(args) == 1:
            first_arg = args[0]
            if error_code:
                resolved_error_code = error_code
                resolved_message = str(first_arg)
            elif str(first_arg) in CANONICAL_SHARED_ERROR_MAP or (isinstance(first_arg, str) and first_arg.isupper() and "_" in first_arg):
                resolved_error_code = str(first_arg)
                resolved_message = str(first_arg)
            else:
                resolved_error_code = error_code or DEST_SPEC_VIOLATION
                resolved_message = str(first_arg)
        else:
            resolved_error_code = error_code or canonical_code or DEST_SPEC_VIOLATION
            resolved_message = kwargs.get("message") or resolved_error_code

        if canonical_code and (not resolved_error_code or resolved_error_code == DEST_SPEC_VIOLATION):
            resolved_error_code = canonical_code

        self.error_code = resolved_error_code
        self.message = resolved_message
        self.status_code = status_code or ERROR_STATUS_MAP.get(
            self.error_code, status.HTTP_400_BAD_REQUEST
        )
        viols = violations or []
        if not viols and details and isinstance(details, dict):
            viols = details.get("violations") or []
        if not viols and "SPEC_VIOLATION" in self.error_code:
            viols = [self.message]
        self.violations = viols
        self.details = details or {}
        super().__init__(self.message)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize error payload to standard dictionary supporting both legacy and Appendix A fields."""
        canonical = CANONICAL_SHARED_ERROR_MAP.get(self.error_code, self.error_code)
        return {
            "error_code": self.error_code,
            "shared_error_code": canonical,
            "code": canonical,
            "message": self.message,
            "detail": self.message,
            "error": self.message,
            "violations": self.violations,
        }


class DestinationSpecViolationError(ConnectorException):
    """Raised when content violates destination character limits or structure."""

    def __init__(self, message: str) -> None:
        super().__init__(ERROR_CODE_SPEC_VIOLATION, message, status.HTTP_400_BAD_REQUEST)


class AuthExpiredError(ConnectorException):
    """Raised when destination authentication or session token is invalid/expired."""

    def __init__(self, message: str = "Destination authentication token or session has expired.") -> None:
        super().__init__(ERROR_CODE_AUTH_EXPIRED, message, status.HTTP_401_UNAUTHORIZED)


class ContentRejectedError(ConnectorException):
    """Raised when destination policy or moderation rejects the content."""

    def __init__(self, message: str = "Content was rejected by destination moderation policy.") -> None:
        super().__init__(ERROR_CODE_CONTENT_REJECTED, message, status.HTTP_403_FORBIDDEN)


class RateLimitedError(ConnectorException):
    """Raised when destination platform rate limit is triggered."""

    def __init__(self, message: str = "Downstream destination rate limit reached. Please retry later.") -> None:
        super().__init__(ERROR_CODE_RATE_LIMITED, message, status.HTTP_429_TOO_MANY_REQUESTS)


class FrequencyCapExceededError(ConnectorException):
    """Raised when application publishing frequency cap is exceeded."""

    def __init__(self, message: str = "Publish frequency cap exceeded for destination.") -> None:
        super().__init__(ERROR_CODE_FREQUENCY_CAP, message, status.HTTP_429_TOO_MANY_REQUESTS)


class QuotaExhaustedError(ConnectorException):
    """Raised when destination posting allocation or quota has been exhausted."""

    def __init__(self, message: str = "Destination publication quota has been exhausted.") -> None:
        super().__init__(ERROR_CODE_QUOTA_EXHAUSTED, message, status.HTTP_429_TOO_MANY_REQUESTS)


class IdempotencyConflictError(ConnectorException):
    """Raised when an idempotency key is reused with a different request payload."""

    def __init__(
        self,
        message: str = "Idempotency key was reused with a different request payload.",
    ) -> None:
        super().__init__(ERROR_CODE_IDEMPOTENCY_CONFLICT, message, status.HTTP_409_CONFLICT)


class ForbiddenError(ConnectorException):
    """Raised when destination action is forbidden (e.g. insufficient OAuth scopes or permissions)."""

    def __init__(self, message: str = "Access to destination action is forbidden.") -> None:
        super().__init__(ERROR_CODE_FORBIDDEN, message, status.HTTP_403_FORBIDDEN)


class NetworkError(ConnectorException):
    """Raised when network connectivity or transport to destination fails."""

    def __init__(self, message: str = "Failed to communicate with destination platform.") -> None:
        super().__init__(ERROR_CODE_NETWORK_ERROR, message, status.HTTP_502_BAD_GATEWAY)


class DestinationError(ConnectorException):
    """Raised when remote destination platform encounters an unexpected or upstream failure."""

    def __init__(self, message: str = "Destination platform encountered an upstream error.") -> None:
        super().__init__(ERROR_CODE_DESTINATION_ERROR, message, status.HTTP_502_BAD_GATEWAY)

