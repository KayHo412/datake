"""Read supported tabular files into pandas DataFrames."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from pandas.errors import EmptyDataError, ParserError

from datake.config import Settings

logger = logging.getLogger(__name__)


@dataclass
class ReadResult:
    """Outcome of attempting to load one file.

    ``dataframe`` is only set on success. Failures keep the error message so
    callers can log, report, and continue without silently dropping the file.
    """

    source_path: Path
    status: str
    dataframe: pd.DataFrame | None = None
    error: str | None = None
    row_count: int = 0
    column_names: list[str] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        return self.status == "success" and self.dataframe is not None


def is_supported_file(path: Path, settings: Settings) -> bool:
    """Return True when *path* has a configured extension."""
    return path.suffix.lower() in settings.supported_extensions


def list_input_files(settings: Settings) -> list[Path]:
    """List supported files in the configured input directory, sorted by name."""
    if not settings.input_dir.exists():
        logger.warning("Input directory does not exist: %s", settings.input_dir)
        return []

    files = [
        path
        for path in settings.input_dir.iterdir()
        if path.is_file() and is_supported_file(path, settings)
    ]
    return sorted(files)


def read_file(path: Path, settings: Settings) -> ReadResult:
    """Read one file without modifying it.

    Original files stay in place. This function only loads data into memory.
    """
    source = path.expanduser().resolve()
    logger.info("Reading file: %s", source)

    if not source.is_file():
        return _failure(source, f"File not found: {source}")

    if not is_supported_file(source, settings):
        supported = ", ".join(settings.supported_extensions)
        return _failure(
            source,
            f"Unsupported file type '{source.suffix}'. Supported: {supported}",
        )

    suffix = source.suffix.lower()
    if suffix == ".csv":
        return _read_csv(source, settings)
    if suffix == ".xlsx":
        return _read_excel(source)
    if suffix == ".json":
        return _read_json(source)
    if suffix == ".jsonl":
        return _read_json_lines(source)
    if suffix == ".parquet":
        return _read_parquet(source)

    return _failure(
        source,
        f"Reader for '{suffix}' is not implemented yet.",
    )


def _read_csv(source: Path, settings: Settings) -> ReadResult:
    last_error: str | None = None
    delimiter = settings.csv_delimiter

    for encoding in settings.csv_encodings:
        try:
            dataframe = pd.read_csv(
                source,
                encoding=encoding,
                sep=delimiter if delimiter is not None else ",",
            )
        except UnicodeDecodeError as exc:
            last_error = f"Encoding '{encoding}' failed: {exc}"
            logger.debug("%s: %s", source.name, last_error)
            continue
        except (EmptyDataError, ParserError, OSError, ValueError) as exc:
            message = f"Could not parse CSV: {exc}"
            logger.error("%s: %s", source.name, message)
            return _failure(source, message)

        if dataframe.empty and len(dataframe.columns) == 0:
            return _failure(source, "CSV file is empty.")

        logger.info(
            "Loaded %s with encoding '%s' (%s rows, %s columns)",
            source.name,
            encoding,
            len(dataframe),
            len(dataframe.columns),
        )
        return ReadResult(
            source_path=source,
            status="success",
            dataframe=dataframe,
            row_count=len(dataframe),
            column_names=[str(column) for column in dataframe.columns],
        )

    return _failure(
        source,
        last_error or "Unable to decode CSV with the configured encodings.",
    )


def _read_excel(source: Path) -> ReadResult:
    try:
        dataframe = pd.read_excel(source, engine="openpyxl")
    except (ImportError, OSError, ValueError) as exc:
        message = f"Could not parse Excel workbook: {exc}"
        logger.error("%s: %s", source.name, message)
        return _failure(source, message)

    if dataframe.empty and len(dataframe.columns) == 0:
        return _failure(source, "Excel workbook is empty.")

    logger.info(
        "Loaded %s (%s rows, %s columns)",
        source.name,
        len(dataframe),
        len(dataframe.columns),
    )
    return ReadResult(
        source_path=source,
        status="success",
        dataframe=dataframe,
        row_count=len(dataframe),
        column_names=[str(column) for column in dataframe.columns],
    )


def _read_json(source: Path) -> ReadResult:
    try:
        dataframe = pd.read_json(source)
    except (ValueError, OSError) as exc:
        return _failure(source, f"Could not parse JSON: {exc}")
    return _success(source, dataframe)


def _read_json_lines(source: Path) -> ReadResult:
    try:
        dataframe = pd.read_json(source, lines=True)
    except (ValueError, OSError) as exc:
        return _failure(source, f"Could not parse JSON Lines: {exc}")
    return _success(source, dataframe)


def _read_parquet(source: Path) -> ReadResult:
    try:
        dataframe = pd.read_parquet(source)
    except (ImportError, OSError, ValueError) as exc:
        return _failure(source, f"Could not parse Parquet: {exc}")
    return _success(source, dataframe)


def _success(source: Path, dataframe: pd.DataFrame) -> ReadResult:
    if dataframe.empty and len(dataframe.columns) == 0:
        return _failure(source, "Dataset is empty.")
    logger.info(
        "Loaded %s (%s rows, %s columns)",
        source.name,
        len(dataframe),
        len(dataframe.columns),
    )
    return ReadResult(
        source_path=source,
        status="success",
        dataframe=dataframe,
        row_count=len(dataframe),
        column_names=[str(column) for column in dataframe.columns],
    )


def _failure(source: Path, message: str) -> ReadResult:
    logger.error("Failed to read %s: %s", source, message)
    return ReadResult(source_path=source, status="failed", error=message)
