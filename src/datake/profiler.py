"""Generate read-only summaries of tabular data."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class ColumnProfile:
    """Summary of one dataset column."""

    name: str
    data_type: str
    missing_count: int
    missing_percent: float
    unique_count: int
    top_values: tuple[dict[str, Any], ...]
    minimum: Any = None
    maximum: Any = None


@dataclass(frozen=True)
class ProfileSummary:
    """Read-only dataset profile."""

    row_count: int
    column_count: int
    duplicate_rows: int
    quality_score: float
    columns: tuple[ColumnProfile, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return asdict(self)


def profile_dataframe(dataframe: pd.DataFrame) -> ProfileSummary:
    """Summarize columns, missing values, duplicates, and numeric ranges."""
    row_count = len(dataframe)
    duplicate_rows = int(dataframe.duplicated().sum())
    columns = tuple(_profile_column(dataframe, column) for column in dataframe)
    total_cells = row_count * len(dataframe.columns)
    missing_cells = int(dataframe.isna().sum().sum())
    missing_ratio = missing_cells / total_cells if total_cells else 0
    duplicate_ratio = duplicate_rows / row_count if row_count else 0
    quality_score = round(max(0.0, 100 - missing_ratio * 50 - duplicate_ratio * 30), 1)
    return ProfileSummary(
        row_count=row_count,
        column_count=len(dataframe.columns),
        duplicate_rows=duplicate_rows,
        quality_score=quality_score,
        columns=columns,
    )


def _profile_column(dataframe: pd.DataFrame, column: Any) -> ColumnProfile:
    series = dataframe[column]
    missing_count = int(series.isna().sum())
    non_missing = series.dropna()
    counts = non_missing.value_counts().head(3)
    top_values = tuple(
        {"value": _json_value(value), "count": int(count)}
        for value, count in counts.items()
    )
    minimum: Any = None
    maximum: Any = None
    if pd.api.types.is_numeric_dtype(series) and not non_missing.empty:
        minimum = _json_value(non_missing.min())
        maximum = _json_value(non_missing.max())
    return ColumnProfile(
        name=str(column),
        data_type=str(series.dtype),
        missing_count=missing_count,
        missing_percent=round(
            missing_count / len(series) * 100 if len(series) else 0.0,
            2,
        ),
        unique_count=int(non_missing.nunique()),
        top_values=top_values,
        minimum=minimum,
        maximum=maximum,
    )


def _json_value(value: Any) -> Any:
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, (pd.Timestamp, pd.Timedelta)):
        return str(value)
    return value
