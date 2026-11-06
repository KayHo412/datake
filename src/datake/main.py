"""Application entry helpers."""

from __future__ import annotations

import logging
from pathlib import Path

from datake.config import Settings, load_settings
from datake.file_reader import ReadResult, list_input_files, read_file
from datake.processor import ProcessResult, process_and_merge, process_file
from datake.validator import ValidationSummary, validate_dataframe

logger = logging.getLogger(__name__)


def configure_logging(settings: Settings) -> None:
    """Send logs to the console and to the configured log file."""
    settings.log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(settings.log_file, encoding="utf-8"),
        ],
        force=True,
    )


def ensure_data_directories(settings: Settings) -> None:
    """Create input, processed, and reports folders if they are missing."""
    for directory in (settings.input_dir, settings.processed_dir, settings.reports_dir):
        directory.mkdir(parents=True, exist_ok=True)


def load_runtime(config_path: Path | None = None) -> Settings:
    """Load settings, configure logging, and ensure data folders exist."""
    settings = load_settings(config_path)
    configure_logging(settings)
    ensure_data_directories(settings)
    return settings


def read_tabular_file(
    path: Path,
    config_path: Path | None = None,
) -> ReadResult:
    """Load settings, prepare folders, and read one file."""
    settings = load_runtime(config_path)
    return read_file(path, settings)


def validate_tabular_file(
    path: Path,
    config_path: Path | None = None,
) -> tuple[ReadResult, ValidationSummary | None]:
    """Read a file and, if that succeeds, produce a validation summary."""
    settings = load_runtime(config_path)
    read_result = read_file(path, settings)
    if not read_result.succeeded or read_result.dataframe is None:
        return read_result, None
    summary = validate_dataframe(
        read_result.dataframe,
        settings,
        source_path=read_result.source_path,
    )
    return read_result, summary


def clean_tabular_file(
    path: Path,
    config_path: Path | None = None,
) -> ProcessResult:
    """Read one file, clean a copy, and write CSV to the processed folder."""
    settings = load_runtime(config_path)
    return process_file(path, settings, write_output=True)


def merge_tabular_files(
    paths: list[Path] | None = None,
    config_path: Path | None = None,
) -> tuple[list[ProcessResult], Path | None]:
    """Clean input files and merge groups that share the same columns."""
    settings = load_runtime(config_path)
    targets = paths if paths else list_input_files(settings)
    results, output_path, _merged = process_and_merge(
        targets,
        settings,
        write_output=True,
    )
    return results, output_path
