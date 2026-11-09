"""Orchestrate cleaning, optional merges, and writing cleaned CSV files.

Input files stay in the input directory. Outputs go to the processed directory.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from datake.cleaner import CleanResult, clean_dataframe
from datake.config import Settings
from datake.file_reader import read_file

logger = logging.getLogger(__name__)


class IncompatibleDatasetsError(Exception):
    """Raised when datasets cannot be concatenated because columns differ."""


@dataclass
class ProcessResult:
    """Outcome of cleaning one file (and optionally writing it)."""

    source_path: Path
    status: str
    output_path: Path | None = None
    rejected_path: Path | None = None
    dataframe: pd.DataFrame | None = None
    clean_result: CleanResult | None = None
    error: str | None = None
    actions: list[str] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        return self.status == "success" and self.dataframe is not None


def process_file(
    path: Path,
    settings: Settings,
    *,
    write_output: bool = True,
) -> ProcessResult:
    """Read, clean, and optionally write one file. The original is not modified."""
    read_result = read_file(path, settings)
    if not read_result.succeeded or read_result.dataframe is None:
        return ProcessResult(
            source_path=read_result.source_path,
            status="failed",
            error=read_result.error,
        )

    cleaned = clean_dataframe(read_result.dataframe, settings)
    output_path: Path | None = None
    if write_output:
        output_path = cleaned_output_path(read_result.source_path, settings)
        write_cleaned_csv(cleaned.dataframe, output_path)
        rejected_path = write_rejected_csv(
            cleaned.rejected_dataframe,
            read_result.source_path,
            settings,
        )
    else:
        rejected_path = None

    return ProcessResult(
        source_path=read_result.source_path,
        status="success",
        output_path=output_path,
        rejected_path=rejected_path,
        dataframe=cleaned.dataframe,
        clean_result=cleaned,
        actions=list(cleaned.actions),
    )


def cleaned_output_path(source: Path, settings: Settings) -> Path:
    """``data/input/foo.csv`` -> ``data/processed/foo_cleaned.csv``."""
    return settings.processed_dir / f"{source.stem}_cleaned.csv"


def write_cleaned_csv(dataframe: pd.DataFrame, output_path: Path) -> Path:
    """Write a cleaned table. Creates the processed folder if needed."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    dataframe.to_csv(output_path, index=False)
    logger.info("Wrote cleaned CSV: %s (%s rows)", output_path, len(dataframe))
    return output_path


def write_rejected_csv(
    dataframe: pd.DataFrame,
    source: Path,
    settings: Settings,
) -> Path | None:
    """Write rejected records when cleaning removed any rows."""
    if dataframe.empty:
        return None
    output_path = settings.quarantine_dir / f"{source.stem}_rejected.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    dataframe.to_csv(output_path, index=False)
    logger.info("Wrote rejected CSV: %s (%s rows)", output_path, len(dataframe))
    return output_path


def merge_dataframes(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Stack tables that share the same columns.

    Column order follows the first frame. Rows are concatenated; remaining
    duplicates across files are then removed.
    """
    if not frames:
        raise IncompatibleDatasetsError("No datasets to merge.")
    expected = list(frames[0].columns)
    expected_set = set(expected)
    for index, frame in enumerate(frames[1:], start=2):
        if set(frame.columns) != expected_set:
            raise IncompatibleDatasetsError(
                f"Dataset {index} columns {list(frame.columns)} do not match "
                f"{expected}."
            )
    aligned = [frames[0]] + [frame[expected] for frame in frames[1:]]
    merged = pd.concat(aligned, ignore_index=True)
    before = len(merged)
    merged = merged.drop_duplicates().reset_index(drop=True)
    removed = before - len(merged)
    if removed:
        logger.info("Removed %s duplicate row(s) after merge", removed)
    return merged


def process_and_merge(
    paths: list[Path],
    settings: Settings,
    *,
    write_output: bool = True,
) -> tuple[list[ProcessResult], Path | None, pd.DataFrame | None]:
    """Clean each path, write individual CSVs, merge compatible groups.

    Files that fail to read are skipped so one bad file does not stop the rest.
    Incompatible column sets are not forced together.
    """
    results: list[ProcessResult] = []
    groups: dict[tuple[str, ...], list[tuple[ProcessResult, pd.DataFrame]]]
    groups = defaultdict(list)

    for path in paths:
        result = process_file(path, settings, write_output=write_output)
        results.append(result)
        if result.succeeded and result.dataframe is not None:
            key = tuple(result.dataframe.columns)
            groups[key].append((result, result.dataframe))

    mergeable = {key: items for key, items in groups.items() if len(items) >= 2}
    if not mergeable:
        logger.info("No compatible dataset groups to merge.")
        return results, None, None

    # If several groups exist, merge the largest; others stay as individual files.
    key = max(mergeable, key=lambda item: len(mergeable[item]))
    frames = [frame for _, frame in mergeable[key]]
    merged = merge_dataframes(frames)
    output_path: Path | None = None
    if write_output:
        output_path = settings.processed_dir / "merged.csv"
        write_cleaned_csv(merged, output_path)
    logger.info(
        "Merged %s compatible files into %s rows",
        len(frames),
        len(merged),
    )
    return results, output_path, merged
