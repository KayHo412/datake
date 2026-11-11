from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from datake.api import create_app
from datake.config import load_settings


def write_settings(tmp_path: Path) -> Path:
    config = tmp_path / "config" / "settings.json"
    config.parent.mkdir()
    config.write_text(
        json.dumps(
            {
                "paths": {
                    "input_dir": "data/input",
                    "processed_dir": "data/processed",
                    "reports_dir": "data/reports",
                    "log_file": "logs/datake.log",
                    "history_db": "data/datake.db",
                },
                "files": {"supported_extensions": [".csv"]},
                "validation": {
                    "required_columns": ["customer_id", "email"],
                    "email_columns": ["email"],
                },
                "cleaning": {
                    "drop_if_missing": ["customer_id", "email"],
                    "drop_invalid_emails": True,
                },
            }
        ),
        encoding="utf-8",
    )
    return config


def test_api_upload_process_report_and_download(tmp_path: Path) -> None:
    settings = load_settings(write_settings(tmp_path))
    client = TestClient(create_app(settings))
    content = b"customer_id,email\n1,ada@example.com\n2,bad-email\n"

    health = client.get("/health")
    uploaded = client.post(
        "/files",
        files={"file": ("customers.csv", content, "text/csv")},
    )

    assert health.status_code == 200
    assert uploaded.status_code == 201
    file_id = uploaded.json()["file_id"]

    processed = client.post(f"/files/{file_id}/process")
    assert processed.status_code == 202
    job = processed.json()
    assert job["status"] == "completed"
    assert job["rows_in"] == 2
    assert job["rows_out"] == 1
    assert job["rejected_rows"] == 1

    report = client.get(f"/jobs/{job['job_id']}/report")
    download = client.get(f"/files/{file_id}/download")
    assert report.status_code == 200
    assert report.json()["rows_out"] == 1
    assert download.status_code == 200
    assert b"ada@example.com" in download.content


def test_api_rejects_unsupported_upload(tmp_path: Path) -> None:
    client = TestClient(create_app(load_settings(write_settings(tmp_path))))

    response = client.post(
        "/files",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )

    assert response.status_code == 415
