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
    job = client.get(f"/jobs/{job['job_id']}").json()
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


def test_api_webhook_writes_json_input(tmp_path: Path) -> None:
    client = TestClient(create_app(load_settings(write_settings(tmp_path))))

    response = client.post(
        "/webhooks/shop",
        json=[{"customer_id": 1, "email": "ada@example.com"}],
    )

    assert response.status_code == 202
    path = Path(response.json()["path"])
    assert path.is_file()
    assert json.loads(path.read_text(encoding="utf-8"))[0]["customer_id"] == 1


def test_job_listing_import_filter_update_and_export(tmp_path: Path) -> None:
    settings = load_settings(write_settings(tmp_path))
    client = TestClient(create_app(settings))

    imported = client.post(
        "/jobs/listings/import",
        files={
            "file": (
                "jobs.json",
                b'[{"title":"Data Analyst","company":"Example","location":"Remote","url":"https://example.test/jobs/1"}]',
                "application/json",
            )
        },
    )
    assert imported.status_code == 201
    assert imported.json()["imported"] == 1

    listings = client.get("/jobs/listings").json()["listings"]
    assert len(listings) == 1
    listing_id = listings[0]["listing_id"]

    updated = client.patch(
        f"/jobs/listings/{listing_id}",
        json={"status": "applied", "notes": "Sent CV"},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "applied"

    filtered = client.get("/jobs/listings?status=applied").json()["listings"]
    assert filtered[0]["notes"] == "Sent CV"

    exported = client.post("/jobs/listings/export")
    assert exported.status_code == 200
    assert exported.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


def test_api_rejects_unsupported_upload(tmp_path: Path) -> None:
    client = TestClient(create_app(load_settings(write_settings(tmp_path))))

    response = client.post(
        "/files",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )

    assert response.status_code == 415


def test_api_requires_configured_api_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATAKE_API_KEY", "test-secret")
    client = TestClient(create_app(load_settings(write_settings(tmp_path))))

    missing = client.get("/jobs/unknown")
    authorized = client.get("/jobs/unknown", headers={"x-api-key": "test-secret"})

    assert missing.status_code == 401
    assert authorized.status_code == 404
    monkeypatch.delenv("DATAKE_API_KEY")


def test_dashboard_returns_processing_and_privacy_metrics(tmp_path: Path) -> None:
    settings = load_settings(write_settings(tmp_path))
    client = TestClient(create_app(settings))
    uploaded = client.post(
        "/files",
        files={
            "file": (
                "customers.csv",
                b"customer_id,email\n1,ada@example.com\n",
                "text/csv",
            )
        },
    )
    client.post(f"/files/{uploaded.json()['file_id']}/process")

    response = client.get("/dashboard")

    assert response.status_code == 200
    payload = response.json()
    assert payload["successful_runs"] == 1
    assert payload["recent_runs"][0]["sensitive_columns"] == {
        "email": "email"
    }
