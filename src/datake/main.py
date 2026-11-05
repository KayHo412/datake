"""Application entry helpers for Phase 1 (file reading)."""

from __future__ import annotations

import logging
from pathlib import Path

from datake.config import Settings, load_settings
from datake.file_reader import ReadResult, read_file

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


def read_tabular_file(
    path: Path,
    config_path: Path | None = None,
) -> ReadResult:
    """Load settings, prepare folders, and read one file."""
    settings = load_settings(config_path)
    configure_logging(settings)
    ensure_data_directories(settings)
    return read_file(path, settings)
