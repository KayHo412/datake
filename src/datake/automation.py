"""Automated processing of files arriving in the input directory."""

from __future__ import annotations

import json
import logging
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path

from datake.config import Settings
from datake.file_reader import list_input_files
from datake.history import ProcessingHistory, file_hash
from datake.processor import ProcessResult, process_file

logger = logging.getLogger(__name__)


def write_report(result: ProcessResult, settings: Settings, digest: str) -> Path:
    """Write a JSON report describing one automated processing run."""
    report_path = settings.reports_dir / f"{result.source_path.stem}_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source_path": str(result.source_path),
        "file_hash": digest,
        "status": result.status,
        "error": result.error,
        "rows_in": result.clean_result.rows_in if result.clean_result else None,
        "rows_out": result.clean_result.rows_out if result.clean_result else None,
        "rejected_rows": (
            len(result.clean_result.rejected_dataframe)
            if result.clean_result
            else None
        ),
        "actions": result.actions,
        "output_path": str(result.output_path) if result.output_path else None,
        "rejected_path": str(result.rejected_path) if result.rejected_path else None,
        "created_at": datetime.now(UTC).isoformat(),
    }
    report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return report_path


def process_new_files(settings: Settings) -> list[ProcessResult]:
    """Process unhandled input files once and archive successful inputs."""
    history = ProcessingHistory(settings)
    results: list[ProcessResult] = []
    for source in list_input_files(settings):
        digest = file_hash(source)
        if history.has_success(digest):
            logger.info("Skipping already processed file: %s", source)
            continue
        result = process_file(source, settings)
        report_path = write_report(result, settings, digest)
        history.record(
            source,
            digest,
            result.status,
            report_path=report_path,
            error=result.error,
        )
        results.append(result)
        destination_dir = (
            settings.archive_dir if result.succeeded else settings.quarantine_dir
        )
        destination_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(_unique_destination(destination_dir, source)))
    return results


def watch_input(
    settings: Settings,
    *,
    once: bool = False,
    interval: float | None = None,
) -> None:
    """Poll the input directory until interrupted, or process one batch."""
    delay = interval if interval is not None else settings.watch_interval
    while True:
        process_new_files(settings)
        if once:
            return
        time.sleep(delay)


def _unique_destination(directory: Path, source: Path) -> Path:
    destination = directory / source.name
    counter = 1
    while destination.exists():
        destination = directory / f"{source.stem}_{counter}{source.suffix}"
        counter += 1
    return destination
