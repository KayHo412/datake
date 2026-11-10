from __future__ import annotations

from pathlib import Path

from datake.config import load_settings
from datake.history import ProcessingHistory


def test_runs_can_be_filtered_by_status(tmp_path: Path) -> None:
    config = tmp_path / "config" / "settings.json"
    config.parent.mkdir()
    config.write_text('{"paths": {"history_db": "data/history.db"}}')
    history = ProcessingHistory(load_settings(config))
    history.record(tmp_path / "ok.csv", "ok-hash", "success")
    history.record(tmp_path / "bad.csv", "bad-hash", "failed", error="broken")

    failed = history.runs(status="failed")

    assert len(failed) == 1
    assert failed[0].source_path == tmp_path / "bad.csv"
    assert failed[0].error == "broken"
