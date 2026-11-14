from __future__ import annotations

import json
from pathlib import Path

from datake.config import load_settings
from datake.jobs import JobStore, run_job


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
                    "archive_dir": "data/archive",
                    "quarantine_dir": "data/quarantine",
                    "history_db": "data/history.db",
                    "log_file": "logs/datake.log",
                },
                "files": {"supported_extensions": [".csv"]},
                "jobs": [
                    {
                        "name": "customers",
                        "interval_seconds": 1,
                        "retries": 1,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "data" / "input").mkdir(parents=True)
    return config


def test_run_job_records_success_and_processes_input(tmp_path: Path) -> None:
    settings = load_settings(write_settings(tmp_path))
    source = settings.input_dir / "customers.csv"
    source.write_text("id,name\n1,Ada\n", encoding="utf-8")

    run = run_job(settings, "customers")

    assert run.status == "success"
    assert run.attempts == 1
    assert run.processed_count == 1
    assert JobStore(settings).runs("customers")[0] == run


def test_dry_run_keeps_input_and_does_not_write_processed_file(tmp_path: Path) -> None:
    settings = load_settings(write_settings(tmp_path))
    source = settings.input_dir / "customers.csv"
    source.write_text("id,name\n1,Ada\n", encoding="utf-8")

    run = run_job(settings, "customers", dry_run=True)

    assert run.status == "success"
    assert source.exists()
    assert not list(settings.processed_dir.glob("*"))
