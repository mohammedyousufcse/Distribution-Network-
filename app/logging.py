"""Structured JSON logging configuration and formatter using Python standard logging."""

import json
import logging
import re
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set
from app.config import get_settings

# Sensitive field name patterns to redact
SENSITIVE_KEYS: Set[str] = {
    "password",
    "pass",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "auth",
    "api_key",
    "apikey",
    "client_secret",
    "private_key",
    "credential",
    "credentials",
}

# Regex to redact Bearer tokens or auth tokens appearing in string text
BEARER_TOKEN_PATTERN = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9_\-\.\~]+", re.IGNORECASE)


def redact_sensitive_data(data: Any) -> Any:
    """Recursively redact sensitive credentials, tokens, and passwords from log data."""
    if isinstance(data, dict):
        redacted_dict: Dict[str, Any] = {}
        for key, value in data.items():
            key_str = str(key).lower()
            if any(sens in key_str for sens in SENSITIVE_KEYS):
                redacted_dict[key] = "[REDACTED]"
            else:
                redacted_dict[key] = redact_sensitive_data(value)
        return redacted_dict
    elif isinstance(data, (list, tuple, set)):
        redacted_list = [redact_sensitive_data(item) for item in data]
        return type(data)(redacted_list) if not isinstance(data, set) else set(redacted_list)
    elif isinstance(data, str):
        return BEARER_TOKEN_PATTERN.sub(r"\1[REDACTED]", data)
    return data


class JSONFormatter(logging.Formatter):
    """Custom logging formatter that serializes log records into standard single-line JSON."""

    # Standard LogRecord attributes to exclude from custom 'extra' payload
    RESERVED_ATTRS: Set[str] = {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "message",
    }

    def format(self, record: logging.LogRecord) -> str:
        """Format the specified record as a JSON string with standardized fields."""
        # 1. Base log record fields
        timestamp = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()
        log_payload: Dict[str, Any] = {
            "timestamp": timestamp,
            "level": record.levelname,
            "logger": record.name,
            "message": redact_sensitive_data(record.getMessage()),
        }

        # 2. Extract and sanitize extra contextual attributes
        for key, value in record.__dict__.items():
            if key not in self.RESERVED_ATTRS:
                log_payload[key] = redact_sensitive_data(value)

        # 3. Add exception traceback if present
        if record.exc_info:
            log_payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_payload, default=str)


def setup_logging(log_level: Optional[str] = None) -> logging.Logger:
    """Configure structured JSON logging to stdout for Docker and local execution."""
    level_name = (log_level or getattr(get_settings(), "LOG_LEVEL", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Check if a JSON stdout StreamHandler is already registered to avoid duplicates
    has_json_handler = False
    for handler in root_logger.handlers:
        if isinstance(handler, logging.StreamHandler) and isinstance(
            handler.formatter, JSONFormatter
        ):
            has_json_handler = True
            break

    if not has_json_handler:
        # Clear existing default handlers to enforce clean single-line JSON
        root_logger.handlers.clear()
        stdout_handler = logging.StreamHandler(sys.stdout)
        stdout_handler.setFormatter(JSONFormatter())
        stdout_handler.setLevel(level)
        root_logger.addHandler(stdout_handler)

    # Also configure application-specific logger hierarchy
    app_logger = logging.getLogger("app")
    app_logger.setLevel(level)

    return app_logger


def get_logger(name: str) -> logging.Logger:
    """Return a standard logger instance for the given module name."""
    return logging.getLogger(name)
