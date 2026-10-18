"""Verification tests for the 150 real researched destination catalogue."""

import csv
from pathlib import Path
import pytest
from app.services.catalogue_import_service import catalogue_import_service


def test_real_catalogue_file_exists_and_count():
    csv_path = Path("data/destinations_real_150.csv")
    assert csv_path.exists(), "data/destinations_real_150.csv must exist."

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))

    assert len(reader) == 150, f"Expected 150 real destinations, found {len(reader)}."

    expected_cols = [
        "name", "url", "platform_key", "surface", "category", "audience_tags",
        "language", "geo", "est_audience", "rules_url", "frequency_cap",
        "self_promo_allowed", "link_policy", "disclosure_required",
        "automation_allowed", "connector_key", "relevance_score",
        "relevance_reason", "level", "last_certified_at"
    ]
    for col in expected_cols:
        assert col in reader[0], f"Missing expected column '{col}'."

    # Validate all 150 rows have valid URLs and relevance score between 1 and 5
    for row in reader:
        assert row["url"].startswith("http")
        score = int(row["relevance_score"])
        assert 1 <= score <= 5
        assert len(row["relevance_reason"]) > 5


def test_real_catalogue_import_service_validation():
    import asyncio
    csv_path = Path("data/destinations_real_150.csv")
    content = csv_path.read_text(encoding="utf-8")
    report = asyncio.run(catalogue_import_service.import_csv_content(content, filename="destinations_real_150.csv", mock_reachability=True))
    assert report["total_rows_processed"] == 150
    assert report["imported_count"] == 150
    assert report["invalid_count"] == 0
    assert report["duplicate_count"] == 0
    assert len(report["errors"]) == 0
