"""
Catalogue Import Service (IncuBrix Advanced Level Requirement).

Validates, de-duplicates, checks reachability, enriches, and imports destination
catalogues from CSV format conforming to the Appendix A 20-column schema.
Supports processing 1,000+ rows in under 5 minutes with a row-by-row error report.
"""

import asyncio
import csv
import io
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse
import httpx

from app.logging import get_logger

logger = get_logger("app.services.catalogue_import")

# The exact 20 columns mandated in Appendix A of the IncuBrix Assessment 4 Brief
EXPECTED_COLUMNS = [
    "name",
    "url",
    "platform_key",
    "surface",
    "category",
    "audience_tags",
    "language",
    "geo",
    "est_audience",
    "rules_url",
    "frequency_cap",
    "self_promo_allowed",
    "link_policy",
    "disclosure_required",
    "automation_allowed",
    "connector_key",
    "relevance_score",
    "relevance_reason",
    "level",
    "last_certified_at",
]

VALID_LEVELS = {"L0", "L1", "L2", "L3", "L4"}
VALID_CONNECTOR_KEYS = {"discourse", "lemmy", "devto", "ghost", "webhook", "assisted", "mock", "mastodon", "hashnode", "slack"}


def normalize_url(raw_url: str) -> str:
    """Normalize URL by stripping whitespace, standardizing protocol, lowercase host, and removing trailing slashes."""
    if not raw_url:
        return ""
    clean = raw_url.strip()
    if not clean.startswith(("http://", "https://")):
        clean = "https://" + clean
    parsed = urlparse(clean)
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    normalized = f"{parsed.scheme.lower()}://{netloc}{path}"
    return normalized


def parse_bool(value: Any, default: bool = False) -> bool:
    """Parse flexible boolean representations."""
    if isinstance(value, bool):
        return value
    val_str = str(value).strip().lower()
    if val_str in ("true", "1", "yes", "t", "y"):
        return True
    if val_str in ("false", "0", "no", "f", "n"):
        return False
    return default


class CatalogueImportReport:
    """Structured report tracking row-by-row import results, errors, and timings."""

    def __init__(self, filename: str = "import.csv"):
        self.filename = filename
        self.start_time = time.perf_counter()
        self.end_time: Optional[float] = None
        self.total_rows = 0
        self.imported_rows = 0
        self.duplicate_rows = 0
        self.invalid_rows = 0
        self.unreachable_rows = 0
        self.errors_by_row: List[Dict[str, Any]] = []
        self.valid_destinations: List[Dict[str, Any]] = []

    def record_error(self, row_index: int, error_type: str, message: str, raw_data: Optional[Dict[str, Any]] = None) -> None:
        self.errors_by_row.append({
            "row": row_index,
            "error_type": error_type,
            "message": message,
            "data_sample": {k: raw_data.get(k) for k in ("name", "url", "platform_key") if raw_data} if raw_data else None,
        })

    def complete(self) -> Dict[str, Any]:
        self.end_time = time.perf_counter()
        elapsed_seconds = round(self.end_time - self.start_time, 2)
        return {
            "file": self.filename,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": elapsed_seconds,
            "total_rows_processed": self.total_rows,
            "imported_count": self.imported_rows,
            "duplicate_count": self.duplicate_rows,
            "invalid_count": self.invalid_rows,
            "unreachable_count": self.unreachable_rows,
            "success_rate_percent": round((self.imported_rows / self.total_rows * 100), 1) if self.total_rows else 0.0,
            "errors": self.errors_by_row,
            "valid_destinations": self.valid_destinations,
            "destinations_sample": self.valid_destinations[:10],
        }


class CatalogueImportService:
    """Service handling high-throughput CSV destination import, de-duplication, and validation."""

    def __init__(self, reachability_timeout: float = 2.0, max_concurrent_probes: int = 50):
        self.reachability_timeout = reachability_timeout
        self.max_concurrent_probes = max_concurrent_probes

    def validate_row_schema(self, row: Dict[str, Any], row_idx: int) -> Tuple[bool, List[str], Dict[str, Any]]:
        """Validate a single CSV dictionary row against schema rules."""
        errors: List[str] = []
        parsed_record: Dict[str, Any] = {}

        # 1. Name & URL
        name = str(row.get("name", "")).strip()
        if not name:
            errors.append("Missing required field: 'name'")
        parsed_record["name"] = name

        raw_url = str(row.get("url", "")).strip()
        if not raw_url:
            errors.append("Missing required field: 'url'")
            norm_url = ""
        else:
            norm_url = normalize_url(raw_url)
            if not norm_url.startswith(("http://", "https://")):
                errors.append(f"Invalid URL schema: '{raw_url}'")
        parsed_record["url"] = norm_url

        # 2. Platform Key & Connector Key
        plat_key = str(row.get("platform_key", "")).strip().lower()
        if not plat_key:
            errors.append("Missing required field: 'platform_key'")
        parsed_record["platform_key"] = plat_key

        conn_key = str(row.get("connector_key", "")).strip().lower() or plat_key
        parsed_record["connector_key"] = conn_key

        # 3. Surface & Category
        parsed_record["surface"] = str(row.get("surface", "post")).strip() or "post"
        parsed_record["category"] = str(row.get("category", "general")).strip() or "general"
        parsed_record["audience_tags"] = [t.strip() for t in str(row.get("audience_tags", "")).split(";") if t.strip()]
        parsed_record["language"] = str(row.get("language", "en")).strip() or "en"
        parsed_record["geo"] = str(row.get("geo", "global")).strip() or "global"

        # 4. Audience estimation
        try:
            parsed_record["est_audience"] = int(row.get("est_audience", 0) or 0)
        except ValueError:
            parsed_record["est_audience"] = 0

        # 5. Policies
        try:
            parsed_record["frequency_cap"] = int(row.get("frequency_cap", 7) or 7)
        except ValueError:
            parsed_record["frequency_cap"] = 7

        parsed_record["self_promo_allowed"] = parse_bool(row.get("self_promo_allowed"), default=True)
        parsed_record["link_policy"] = str(row.get("link_policy", "allowed")).strip().lower()
        parsed_record["disclosure_required"] = parse_bool(row.get("disclosure_required"), default=False)
        parsed_record["automation_allowed"] = parse_bool(row.get("automation_allowed"), default=True)

        # 6. Relevance Score (1-5)
        try:
            rel_score = int(row.get("relevance_score", 3) or 3)
            if not 1 <= rel_score <= 5:
                errors.append(f"Relevance score must be an integer between 1 and 5, got {rel_score}")
        except ValueError:
            errors.append(f"Invalid relevance score format: {row.get('relevance_score')}")
            rel_score = 3
        parsed_record["relevance_score"] = rel_score
        parsed_record["relevance_reason"] = str(row.get("relevance_reason", "")).strip()

        # 7. Level (L0-L4)
        lvl = str(row.get("level", "L0")).strip().upper()
        if lvl not in VALID_LEVELS:
            errors.append(f"Invalid level '{lvl}'. Must be one of: {sorted(VALID_LEVELS)}")
            lvl = "L0"
        parsed_record["level"] = lvl
        parsed_record["last_certified_at"] = str(row.get("last_certified_at", "")).strip() or None

        is_valid = len(errors) == 0
        return is_valid, errors, parsed_record

    async def _probe_reachability_batch(self, urls: List[str], mock_mode: bool = False) -> Dict[str, bool]:
        """Check reachability of a list of URLs concurrently using HTTP HEAD/GET probes."""
        results: Dict[str, bool] = {}
        if mock_mode:
            # In mock or benchmark test mode, simulate fast reachability checks
            for u in urls:
                results[u] = not u.endswith(".invalid") and "nonexistent" not in u
            return results

        semaphore = asyncio.Semaphore(self.max_concurrent_probes)

        async def probe(client: httpx.AsyncClient, url: str) -> None:
            async with semaphore:
                try:
                    resp = await client.head(url, follow_redirects=True)
                    results[url] = resp.status_code < 500
                except Exception:
                    try:
                        resp = await client.get(url, follow_redirects=True)
                        results[url] = resp.status_code < 500
                    except Exception:
                        results[url] = False

        async with httpx.AsyncClient(timeout=self.reachability_timeout) as client:
            tasks = [probe(client, url) for url in urls]
            await asyncio.gather(*tasks, return_exceptions=True)

        return results

    async def import_csv_content(
        self,
        csv_text: str,
        filename: str = "destinations.csv",
        check_reachability: bool = True,
        mock_reachability: bool = False,
    ) -> Dict[str, Any]:
        """
        Import destinations from a CSV string.
        De-duplicates by (normalized_url, platform_key).
        Validates schema, checks reachability, and returns full audit report.
        """
        report = CatalogueImportReport(filename=filename)
        reader = csv.DictReader(io.StringIO(csv_text))

        if not reader.fieldnames:
            report.record_error(0, "EMPTY_FILE", "CSV file contains no headers or data.")
            return report.complete()

        # Check required columns
        header_set = set(reader.fieldnames)
        missing_critical = {"name", "url", "platform_key"} - header_set
        if missing_critical:
            report.record_error(0, "HEADER_MISMATCH", f"Missing critical headers: {sorted(missing_critical)}")
            return report.complete()

        seen_keys: Set[Tuple[str, str]] = set()
        candidate_records: List[Tuple[int, Dict[str, Any]]] = []
        urls_to_probe: Set[str] = set()

        # Step 1: Parse and validate schema
        for row_idx, row in enumerate(reader, start=1):
            report.total_rows += 1
            is_valid, errors, record = self.validate_row_schema(row, row_idx)

            if not is_valid:
                report.invalid_rows += 1
                for err in errors:
                    report.record_error(row_idx, "SCHEMA_VALIDATION_ERROR", err, row)
                continue

            # De-duplication key: (normalized_url, platform_key)
            dedup_key = (record["url"], record["platform_key"])
            if dedup_key in seen_keys:
                report.duplicate_rows += 1
                report.record_error(
                    row_idx,
                    "DUPLICATE_ENTRY",
                    f"Duplicate destination '{record['name']}' with URL '{record['url']}' and platform '{record['platform_key']}'",
                    row,
                )
                continue

            seen_keys.add(dedup_key)
            candidate_records.append((row_idx, record))
            if check_reachability and record["url"]:
                urls_to_probe.add(record["url"])

        # Step 2: Concurrent Reachability Check
        reachability_map: Dict[str, bool] = {}
        if check_reachability and urls_to_probe:
            reachability_map = await self._probe_reachability_batch(list(urls_to_probe), mock_mode=mock_reachability)

        # Step 3: Finalize records and enrich
        for row_idx, record in candidate_records:
            url = record["url"]
            if check_reachability and not reachability_map.get(url, True):
                report.unreachable_rows += 1
                report.record_error(
                    row_idx,
                    "UNREACHABLE_HOST",
                    f"Destination host '{url}' is unreachable or returned HTTP 5xx.",
                    record,
                )
                continue

            # Enriched stable ID
            clean_name = record["name"].lower().replace(" ", "_").replace("-", "_")
            record["id"] = f"{record['connector_key']}_{clean_name[:24]}"
            report.valid_destinations.append(record)
            report.imported_rows += 1

        return report.complete()


catalogue_import_service = CatalogueImportService()
