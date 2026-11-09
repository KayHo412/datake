from __future__ import annotations

import json
from pathlib import Path

from datake.automation import process_new_files
from datake.config import load_settings


def write_settings(tmp_path: Path) -> Path:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    path = config_dir / "settings.json"
    path.write_text(
        json.dumps(
            {
                "paths": {
                    "input_dir": "data/input",
                    "processed_dir": "data/processed",
                    "reports_dir": "data/reports",
                    "log_file": "logs/datake.log",
                    "archive_dir": "data/archive",
                    "quarantine_dir": "data/quarantine",
                    "history_db": "data/datake.db",
                },
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
    (tmp_path / "data" / "input").mkdir(parents=True)
    return path


def test_process_new_files_archives_and_skips_same_content(tmp_path: Path) -> None:
    settings = load_settings(write_settings(tmp_path))
    source = settings.input_dir / "customers.csv"
    source.write_text(
        "customer_id,email\n1,ada@example.com\n2,not-an-email\n",
        encoding="utf-8",
    )

    results = process_new_files(settings)

    assert len(results) == 1
    assert results[0].succeeded
    assert not source.exists()
    assert (settings.archive_dir / source.name).exists()
    assert results[0].rejected_path is not None
    assert results[0].rejected_path.exists()
    report = settings.reports_dir / "customers_report.json"
    assert json.loads(report.read_text(encoding="utf-8"))["rejected_rows"] == 1
    assert process_new_files(settings) == []
