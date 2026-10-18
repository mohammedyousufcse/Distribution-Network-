"""
Assisted connector for semi-automated / manual posting destinations.

Follows the IncuBrix connector specification for destinations where automated
publishing is prohibited or restricted by terms of service. Generates a structured
ready-to-post package ("assist pack") for human operators.
"""

from typing import Any, Dict, List, Optional
import uuid

from app.connectors.base import BaseConnector
from app.models.errors import (
    ConnectorException,
    CANONICAL_DEST_SPEC_VIOLATION,
)
from app.models.payloads import ContentPayload, PublishResult
from app.models.policy import ValidationResult


class AssistedConnector(BaseConnector):
    """
    Assisted connector that generates a ready-to-post assist package
    rather than executing automated HTTP submission.
    """

    name = "assisted"

    def get_manifest(self) -> Dict[str, Any]:
        return {
            "key": "assisted",
            "name": "Assisted Manual-Post Connector",
            "version": "1.0.0",
            "tier": "tier_1",
            "auth": {
                "type": "none",
                "note": "Operator-driven; no automated API tokens stored",
            },
            "surfaces": ["community_submission", "moderated_forum", "manual_board"],
            "content_types": ["text", "markdown", "rich_text"],
            "specification_limits": {
                "max_text_length": 50000,
            },
            "rate_limits": {
                "requests_per_minute": 60,
            },
            "capabilities": {
                "publish": True,
                "get_status": True,
                "delete": True,
                "fetch_metrics": False,
                "refresh_auth": False,
                "build_assist_pack": True,
            },
            "error_map": {
                "400": CANONICAL_DEST_SPEC_VIOLATION,
            },
        }

    def validate(self, payload: ContentPayload) -> ValidationResult:
        errors = []
        text = payload.text or ""

        if not text.strip():
            errors.append("Assisted package text cannot be empty.")
        if len(text) > 50000:
            errors.append("Content exceeds maximum length of 50,000 characters.")

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            ok=len(errors) == 0,
            violations=errors,
        )

    def build_assist_pack(
        self,
        payload: ContentPayload,
        destination: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Generate structured ready-to-post package for human operator."""
        deep_link = destination.get("submission_url") or destination.get("base_url") or "https://incubrix.internal/assist/manual-submit"
        dest_name = destination.get("name") or destination.get("destination_id") or "Target Destination"

        checklist: List[str] = [
            f"Review destination rules for '{dest_name}'.",
            "Ensure disclosure and formatting standards match community guidelines.",
            "Verify no self-promotional spam flags are triggered.",
            "Confirm media files or attachments are downloaded.",
            "Paste formatted text into the destination submission portal.",
            "Mark assist pack as completed after manual post submission.",
        ]

        if payload.metadata and payload.metadata.get("contains_ai"):
            checklist.insert(1, "Include required AI-assistance disclosure notice.")

        media_files = []
        if payload.media_urls:
            media_files = [{"url": u, "type": "remote_media"} for u in payload.media_urls]

        return {
            "destination_id": destination.get("id") or destination.get("destination_id"),
            "destination_name": dest_name,
            "deep_link": deep_link,
            "caption": payload.text,
            "title": payload.title or "",
            "files": media_files,
            "checklist": checklist,
            "status": "human_action_required",
        }

    async def publish(
        self,
        payload: ContentPayload,
        destination: Dict[str, Any],
        connection: Dict[str, Any],
        idempotency_key: Optional[str] = None,
    ) -> PublishResult:
        val = self.validate(payload)
        if not val.valid:
            raise ConnectorException(
                f"Validation failed: {', '.join(val.errors)}",
                status_code=400,
                error_code=CANONICAL_DEST_SPEC_VIOLATION,
                canonical_code=CANONICAL_DEST_SPEC_VIOLATION,
                details={"violations": val.violations},
            )

        pack_id = f"pack_{idempotency_key or uuid.uuid4().hex[:12]}"
        assist_pack = self.build_assist_pack(payload, destination)
        deep_link = assist_pack["deep_link"]

        return PublishResult(
            platform_post_id=pack_id,
            url=deep_link,
            status="human_action_required",
            metadata={
                "assisted": True,
                "assist_pack": assist_pack,
                "operator_instruction": "Open the deep link and complete submission following the checklist.",
            },
        )

    async def get_status(
        self,
        platform_post_id: str,
        destination: Dict[str, Any],
        connection: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "platform_post_id": platform_post_id,
            "status": "human_action_required",
            "live_url": destination.get("submission_url") or destination.get("base_url"),
            "note": "Awaiting human operator submission confirmation.",
        }

    async def delete(
        self,
        platform_post_id: str,
        destination: Dict[str, Any],
        connection: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "deleted": True,
            "platform_post_id": platform_post_id,
            "status": "cancelled",
            "note": "Assisted package cancelled. No remote platform post was created.",
        }
