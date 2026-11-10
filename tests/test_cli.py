from __future__ import annotations

import json
from pathlib import Path

from datake.cli import main
from datake.config import load_settings
from datake.history import ProcessingHistory


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
                    "history_db": "data/datake.db",
                }
            }
        ),
        encoding="utf-8",
    )
    return path


def test_status_json_output(tmp_path: Path, capsys) -> None:
    config_path = write_settings(tmp_path)
    settings = load_settings(config_path)
    history = ProcessingHistory(settings)
    history.record(
        tmp_path / "data" / "input" / "customers.csv",
        "abc123",
        "success",
    )

    exit_code = main(
        [
            "--config",
            str(config_path),
            "status",
            "--json",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["total"] == 1
    assert payload["successful"] == 1
    assert payload["failed"] == 0
    assert payload["recent_runs"][0]["file_hash"] == "abc123"


def test_report_json_output_can_filter_failures(tmp_path: Path, capsys) -> None:
    config_path = write_settings(tmp_path)
    settings = load_settings(config_path)
    ProcessingHistory(settings).record(
        tmp_path / "data" / "input" / "bad.csv",
        "bad-hash",
        "failed",
        error="invalid CSV",
    )

    exit_code = main(
        [
            "--config",
            str(config_path),
            "report",
            "--status",
            "failed",
            "--json",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload) == 1
    assert payload[0]["status"] == "failed"
    assert payload[0]["error"] == "invalid CSV"
