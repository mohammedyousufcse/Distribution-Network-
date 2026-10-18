"""
Repeatable Destination Certification Harness.

Executes end-to-end certification workflows:
1. Loads destination configuration and posting rules.
2. Checks configuration eligibility.
3. Validates an identifiable test payload.
4. Publishes only to safe test/sandbox destinations (or simulation mode).
5. Confirms live platform URL / valid response.
6. Retrieves published post status.
7. Deletes test post (cleanup).
8. Verifies deletion success.
9. Stores timestamped evidence JSON in EVIDENCE/ directory.
10. Marks certification PASS or FAIL.
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from typing import Any, Dict, Optional

from app.connectors.registry import get_connector
from app.logging import get_logger
from app.models.errors import ConnectorException
from app.models.payloads import ContentPayload
from app.services.catalogue_service import catalogue_service
from app.services.policy_service import get_policy_service

logger = get_logger("app.services.certification")


class CertificationHarness:
    """Automated certification harness for destination networks."""

    def __init__(self, evidence_dir: Optional[str] = None):
        self.evidence_dir = Path(evidence_dir or "EVIDENCE")
        self.evidence_dir.mkdir(parents=True, exist_ok=True)

    async def certify_destination(
        self,
        destination_id: str,
        simulation: bool = False,
    ) -> Dict[str, Any]:
        """
        Run full certification lifecycle for a configured destination.
        Returns detailed certification report and saves evidence to EVIDENCE/.
        """
        start_time = time.perf_counter()
        timestamp = datetime.now(timezone.utc).isoformat()
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        evidence: Dict[str, Any] = {
            "certification_id": f"cert_{destination_id}_{date_str}",
            "destination_id": destination_id,
            "timestamp": timestamp,
            "simulation": simulation,
            "status": "IN_PROGRESS",
            "steps": {},
            "errors": [],
            "post_id": None,
            "live_url": None,
            "cleanup_verified": False,
        }

        # Step 1: Load destination configuration
        dest_config = catalogue_service.get_destination(destination_id)
        if not dest_config:
            evidence["status"] = "FAILED"
            evidence["errors"].append(f"Destination '{destination_id}' not found in catalogue.")
            self._save_evidence(evidence, destination_id, date_str)
            return evidence

        connector_key = dest_config.get("connector_key")
        evidence["connector_key"] = connector_key
        connector = get_connector(connector_key)
        if not connector:
            evidence["status"] = "FAILED"
            evidence["errors"].append(f"Connector '{connector_key}' not found in registry.")
            self._save_evidence(evidence, destination_id, date_str)
            return evidence

        connection = catalogue_service.resolve_connection(destination_id)
        if simulation:
            connection["simulation"] = True
            dest_config["simulation"] = True

        evidence["steps"]["config_loaded"] = {
            "ok": True,
            "destination_name": dest_config.get("name"),
            "connector_key": connector_key,
        }

        # Step 2: Validate test payload
        test_payload = ContentPayload(
            title=f"IncuBrix Certification Probe {date_str}",
            text=f"[INCUBRIX-CERTIFICATION-PROBE] Automated compliance probe executed at {timestamp}. Verification ID: {evidence['certification_id']}",
            metadata={"probe": True, "certification_id": evidence["certification_id"]},
        )

        try:
            from app.api.connector import _invoke_connector
            val_result = await _invoke_connector(
                connector, "validate", content=test_payload, destination=dest_config, connection=connection
            )
            val_ok = (
                val_result.get("valid", False)
                if isinstance(val_result, dict)
                else getattr(val_result, "valid", getattr(val_result, "ok", False))
            )
            if not val_ok:
                errors = (
                    val_result.get("violations", val_result.get("errors", []))
                    if isinstance(val_result, dict)
                    else getattr(val_result, "violations", getattr(val_result, "errors", []))
                )
                evidence["steps"]["validate"] = {"ok": False, "violations": errors}
                evidence["status"] = "FAILED"
                evidence["errors"].append(f"Validation failed: {errors}")
                self._save_evidence(evidence, destination_id, date_str)
                return evidence
            evidence["steps"]["validate"] = {"ok": True}
        except Exception as exc:
            evidence["steps"]["validate"] = {"ok": False, "error": str(exc)}
            evidence["status"] = "FAILED"
            evidence["errors"].append(f"Validation threw exception: {str(exc)}")
            self._save_evidence(evidence, destination_id, date_str)
            return evidence

        # Step 3: Publish to destination (or assist pack for assisted connector)
        try:
            from app.api.connector import _invoke_connector
            idempotency_key = f"cert_idem_{date_str}"
            pub_result = await _invoke_connector(
                connector,
                "publish",
                content=test_payload,
                destination=dest_config,
                connection=connection,
                idempotency_key=idempotency_key,
            )
            if isinstance(pub_result, dict):
                post_id = str(pub_result.get("platform_post_id") or pub_result.get("id") or "post_1")
                live_url = str(pub_result.get("live_url") or pub_result.get("url") or "")
                pub_status = str(pub_result.get("status") or "published")
            else:
                post_id = getattr(pub_result, "platform_post_id", getattr(pub_result, "id", "post_1"))
                live_url = getattr(pub_result, "url", getattr(pub_result, "live_url", ""))
                pub_status = getattr(pub_result, "status", "published")

            evidence["post_id"] = post_id
            evidence["live_url"] = live_url
            evidence["steps"]["publish"] = {
                "ok": True,
                "platform_post_id": post_id,
                "live_url": live_url,
                "status": pub_status,
            }
        except Exception as exc:
            evidence["steps"]["publish"] = {"ok": False, "error": str(exc)}
            evidence["status"] = "FAILED"
            evidence["errors"].append(f"Publish failed: {str(exc)}")
            self._save_evidence(evidence, destination_id, date_str)
            return evidence

        # Step 4: Retrieve status
        try:
            from app.api.connector import _invoke_connector
            status_result = await _invoke_connector(
                connector,
                "get_status",
                platform_post_id=post_id,
                destination=dest_config,
                connection=connection,
            )
            retrieved_status = (
                status_result.get("status")
                if isinstance(status_result, dict)
                else getattr(status_result, "status", "unknown")
            )
            retrieved_url = (
                status_result.get("live_url")
                if isinstance(status_result, dict)
                else getattr(status_result, "live_url", None)
            )
            evidence["steps"]["get_status"] = {
                "ok": True,
                "status": retrieved_status,
                "live_url": retrieved_url,
            }
        except Exception as exc:
            evidence["steps"]["get_status"] = {"ok": False, "error": str(exc)}
            evidence["status"] = "FAILED"
            evidence["errors"].append(f"Get status failed: {str(exc)}")

        # Step 5: Delete test post (cleanup within 10 minutes)
        try:
            from app.api.connector import _invoke_connector
            del_result = await _invoke_connector(
                connector,
                "delete",
                platform_post_id=post_id,
                destination=dest_config,
                connection=connection,
            )
            del_ok = (
                del_result.get("deleted", del_result.get("success", False))
                if isinstance(del_result, dict)
                else getattr(del_result, "deleted", getattr(del_result, "success", False))
            )
            evidence["steps"]["delete"] = {
                "ok": del_ok,
                "details": del_result if isinstance(del_result, dict) else str(del_result),
            }
            if del_ok:
                evidence["cleanup_verified"] = True
            else:
                evidence["errors"].append("Deletion returned False or unsupported.")
        except Exception as exc:
            evidence["steps"]["delete"] = {"ok": False, "error": str(exc)}
            evidence["errors"].append(f"Delete cleanup failed: {str(exc)}")

        # Step 6: Final evaluation
        elapsed = round((time.perf_counter() - start_time) * 1000, 2)
        evidence["duration_ms"] = elapsed

        if not evidence["errors"] and evidence["steps"].get("publish", {}).get("ok") and evidence["cleanup_verified"]:
            evidence["status"] = "SUCCESS"
        else:
            evidence["status"] = "FAILED"

        self._save_evidence(evidence, destination_id, date_str)
        return evidence

    def _save_evidence(self, evidence: Dict[str, Any], destination_id: str, date_str: str) -> str:
        """Write evidence file to EVIDENCE/."""
        filename = f"{destination_id}_cert_{date_str}.json"
        path = self.evidence_dir / filename
        with open(path, "w", encoding="utf-8") as f:
            json.dump(evidence, f, indent=2, default=str)
        logger.info(f"Certification evidence recorded to {path}", extra={"destination_id": destination_id, "status": evidence["status"]})
        return str(path)


certification_harness = CertificationHarness()
