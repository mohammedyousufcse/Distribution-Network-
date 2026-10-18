"""Unit and integration tests for the IncuBrix Batch Runner CLI."""

import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.main import app
from batch_runner import execute_test_item, run_batch

client = TestClient(app)


def test_batch_runner_single_item():
    item = {
        "name": "unit_health_check",
        "endpoint": "/health",
        "http_method": "GET",
    }
    res = execute_test_item(client, "http://testserver", item)
    assert res["success"] is True
    assert res["status_code"] == 200
    assert res["response"]["status"] in ("ok", "healthy")
    assert res["duration_ms"] >= 0


def test_batch_runner_full_run(tmp_path: Path):
    input_dir = tmp_path / "inputs"
    output_dir = tmp_path / "outputs"
    input_dir.mkdir()

    # Create 2 test input files
    (input_dir / "01_test.json").write_text(
        json.dumps({"name": "test_health", "endpoint": "/health", "http_method": "GET"}),
        encoding="utf-8",
    )
    (input_dir / "02_test.json").write_text(
        json.dumps({
            "name": "test_mock_publish",
            "endpoint": "/connector/v1/mock/publish",
            "http_method": "POST",
            "body": {"content": {"text": "Batch runner sample post"}},
        }),
        encoding="utf-8",
    )

    summary = run_batch(input_path=input_dir, output_dir=output_dir, api_url="http://testserver", client=client)
    assert summary["total_tests"] == 2
    assert summary["passed"] == 2
    assert summary["failed"] == 0
    assert summary["success_rate_percent"] == 100.0
    assert (output_dir / "summary.json").exists()
    assert (output_dir / "test_health_result.json").exists()
    assert (output_dir / "test_mock_publish_result.json").exists()
