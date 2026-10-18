"""Destination policy service for content validation and in-memory frequency-cap tracking."""

import time
from collections import defaultdict
from typing import Any, Dict, List, Optional
from app.models.policy import (
    DestinationPolicy,
    ERROR_CODE_FREQUENCY_CAP,
    ERROR_CODE_SPEC_VIOLATION,
)


class PolicyService:
    """Service enforcing destination policies, text length limits, and frequency capping.

    NOTE ON STATE PERSISTENCE:
    Frequency-cap request history is stored entirely IN-MEMORY (`self._publish_timestamps`).
    State will reset upon application restart or when `reset()` is explicitly invoked.
    """

    def __init__(self, clock: Optional[Any] = None) -> None:
        """Initialize default policies and in-memory request timestamps."""
        self._clock = clock or time.time
        self._policies: Dict[str, DestinationPolicy] = {
            "mock": DestinationPolicy(
                destination_key="mock",
                max_text_length=280,
                max_requests_per_window=5,
                window_seconds=60,
            ),
            "mastodon": DestinationPolicy(
                destination_key="mastodon",
                max_text_length=500,
                max_requests_per_window=10,
                window_seconds=60,
            ),
        }
        # In-memory mapping: destination_key -> list of epoch timestamps
        self._publish_timestamps: Dict[str, List[float]] = defaultdict(list)

    def set_clock(self, clock: Any) -> None:
        """Inject a custom clock function for deterministic testing."""
        self._clock = clock

    def _now(self) -> float:
        """Get current timestamp using configured clock."""
        return float(self._clock())

    def get_policy(self, destination_key: str) -> DestinationPolicy:
        """Retrieve policy for a destination, or return default policy if not customized."""
        key = destination_key.strip().lower()
        if key not in self._policies:
            return DestinationPolicy(destination_key=key)
        return self._policies[key]

    def set_policy(self, destination_key: str, policy: DestinationPolicy) -> None:
        """Register or update a policy for a destination platform."""
        key = destination_key.strip().lower()
        self._policies[key] = policy

    def validate_content(
        self,
        destination_key: str,
        content: Any,
    ) -> Dict[str, Any]:
        """Validate content structure, length, and posting rules.

        Args:
            destination_key: Target destination key (e.g. 'mock').
            content: Content dictionary to evaluate.

        Returns:
            Dict containing 'valid', 'ok', 'error_code', 'shared_error_code', 'error', and 'violations'.
        """
        if not isinstance(content, dict):
            msg = "Content must be a dictionary."
            return {
                "valid": False,
                "ok": False,
                "error_code": ERROR_CODE_SPEC_VIOLATION,
                "shared_error_code": "DEST_SPEC_VIOLATION",
                "error": msg,
                "violations": [msg],
            }

        text = content.get("text")
        if not isinstance(text, str) or not text.strip():
            msg = "Content must contain a non-empty 'text' field."
            return {
                "valid": False,
                "ok": False,
                "error_code": ERROR_CODE_SPEC_VIOLATION,
                "shared_error_code": "DEST_SPEC_VIOLATION",
                "error": msg,
                "violations": [msg],
            }

        policy = self.get_policy(destination_key)
        text_length = len(text)

        # 1. Format/Length constraints
        if text_length > policy.max_text_length:
            msg = (
                f"Content text length ({text_length}) exceeds maximum allowed "
                f"limit of {policy.max_text_length} characters for '{policy.destination_key}'."
            )
            return {
                "valid": False,
                "ok": False,
                "error_code": ERROR_CODE_SPEC_VIOLATION,
                "shared_error_code": "DEST_SPEC_VIOLATION",
                "error": msg,
                "violations": [msg],
            }

        if text_length < policy.min_text_length:
            msg = (
                f"Content text length ({text_length}) is below minimum allowed "
                f"limit of {policy.min_text_length} characters for '{policy.destination_key}'."
            )
            return {
                "valid": False,
                "ok": False,
                "error_code": ERROR_CODE_SPEC_VIOLATION,
                "shared_error_code": "DEST_SPEC_VIOLATION",
                "error": msg,
                "violations": [msg],
            }

        # 2. Link restrictions
        if not policy.allow_links:
            lower_text = text.lower()
            if "http://" in lower_text or "https://" in lower_text or "www." in lower_text:
                msg = f"Destination '{policy.destination_key}' policy prohibits external hyperlinks."
                return {
                    "valid": False,
                    "ok": False,
                    "error_code": ERROR_CODE_SPEC_VIOLATION,
                    "shared_error_code": "DEST_SPEC_VIOLATION",
                    "error": msg,
                    "violations": [msg],
                }

        # 3. Self-promotion restrictions
        if not policy.allow_self_promotion:
            is_promo = content.get("is_promo") or content.get("is_promotion") or content.get("promotional")
            promo_keywords = ("buy now", "discount", "coupon", "limited offer", "sale on now", "sponsored")
            lower_text = text.lower()
            if is_promo or any(kw in lower_text for kw in promo_keywords):
                msg = f"Destination '{policy.destination_key}' policy prohibits promotional or commercial content."
                return {
                    "valid": False,
                    "ok": False,
                    "error_code": ERROR_CODE_SPEC_VIOLATION,
                    "shared_error_code": "DEST_SPEC_VIOLATION",
                    "error": msg,
                    "violations": [msg],
                }

        # 4. AI-content disclosure requirement
        if policy.require_ai_disclosure:
            is_ai = content.get("is_ai_generated") or content.get("ai_generated")
            has_disclosure = content.get("has_ai_disclosure") or ("#ai" in text.lower()) or ("ai generated" in text.lower())
            if is_ai and not has_disclosure:
                msg = f"Destination '{policy.destination_key}' policy requires explicit AI-content disclosure."
                return {
                    "valid": False,
                    "ok": False,
                    "error_code": ERROR_CODE_SPEC_VIOLATION,
                    "shared_error_code": "DEST_SPEC_VIOLATION",
                    "error": msg,
                    "violations": [msg],
                }

        return {
            "valid": True,
            "ok": True,
            "violations": [],
        }

    def check_and_record_publish(self, destination_key: str) -> Dict[str, Any]:
        """Enforce in-memory frequency caps (window and weekly) for publish actions.

        Prunes timestamps outside active windows. If limits are exceeded,
        rejects with FREQUENCY_CAP_EXCEEDED / DEST_RULE_FREQUENCY_CAP.
        Otherwise records current timestamp and permits publishing.
        """
        key = destination_key.strip().lower()
        policy = self.get_policy(key)
        now = self._now()
        window_start = now - policy.window_seconds
        week_start = now - (7 * 86400)  # 7 days

        # Prune expired timestamps older than 7 days
        all_timestamps = [t for t in self._publish_timestamps[key] if t >= week_start]
        self._publish_timestamps[key] = all_timestamps

        # Check short-term window cap
        window_timestamps = [t for t in all_timestamps if t >= window_start]
        if len(window_timestamps) >= policy.max_requests_per_window:
            msg = (
                f"Publish rate limit exceeded for destination '{key}'. "
                f"Maximum {policy.max_requests_per_window} requests allowed per {policy.window_seconds}s."
            )
            return {
                "allowed": False,
                "error_code": ERROR_CODE_FREQUENCY_CAP,
                "shared_error_code": "DEST_RULE_FREQUENCY_CAP",
                "error": msg,
                "violations": [msg],
            }

        # Check weekly cap if configured
        if policy.weekly_frequency_cap is not None and len(all_timestamps) >= policy.weekly_frequency_cap:
            msg = (
                f"Weekly publish limit exceeded for destination '{key}'. "
                f"Maximum {policy.weekly_frequency_cap} requests allowed per 7-day window."
            )
            return {
                "allowed": False,
                "error_code": ERROR_CODE_FREQUENCY_CAP,
                "shared_error_code": "DEST_RULE_FREQUENCY_CAP",
                "error": msg,
                "violations": [msg],
            }

        # Record this successful publish attempt
        self._publish_timestamps[key].append(now)
        return {
            "allowed": True,
        }

    def reset(self) -> None:
        """Clear all in-memory publish timestamps and restore default policies."""
        self._clock = time.time
        self._publish_timestamps.clear()
        self._policies = {
            "mock": DestinationPolicy(
                destination_key="mock",
                max_text_length=280,
                max_requests_per_window=5,
                window_seconds=60,
            ),
            "mastodon": DestinationPolicy(
                destination_key="mastodon",
                max_text_length=500,
                max_requests_per_window=10,
                window_seconds=60,
            ),
        }


# Global singleton instance for application runtime
_POLICY_SERVICE = PolicyService()


def get_policy_service() -> PolicyService:
    """Return the global PolicyService instance."""
    return _POLICY_SERVICE
