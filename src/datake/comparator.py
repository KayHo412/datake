"""Compare two tabular datasets without modifying either source."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class ComparisonSummary:
    """Counts and examples describing changes between two datasets."""

    key_columns: tuple[str, ...]
    added_count: int
    removed_count: int
    changed_count: int
    added_examples: tuple[dict[str, Any], ...]
    removed_examples: tuple[dict[str, Any], ...]
    changed_examples: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compare_dataframes(
    before: pd.DataFrame,
    after: pd.DataFrame,
    key_columns: list[str] | None = None,
) -> ComparisonSummary:
    """Compare rows by keys, or by complete row values when no keys are given."""
    keys = tuple(key_columns or ())
    if keys:
        missing = [key for key in keys if key not in before or key not in after]
        if missing:
            joined = ", ".join(missing)
            raise ValueError(f"Key column(s) not found in both files: {joined}")
        if before.duplicated(list(keys)).any() or after.duplicated(list(keys)).any():
            raise ValueError("Key columns must identify unique rows in both files.")
        return _compare_by_keys(before, after, keys)
    return _compare_complete_rows(before, after)


def _compare_by_keys(
    before: pd.DataFrame,
    after: pd.DataFrame,
    keys: tuple[str, ...],
) -> ComparisonSummary:
    before_rows = before.set_index(list(keys), drop=False)
    after_rows = after.set_index(list(keys), drop=False)
    added_keys = after_rows.index.difference(before_rows.index)
    removed_keys = before_rows.index.difference(after_rows.index)
    shared = before_rows.index.intersection(after_rows.index)
    comparable = [column for column in before.columns if column in after.columns]
    changed = [
        key
        for key in shared
        if not before_rows.loc[key, comparable].equals(
            after_rows.loc[key, comparable]
        )
    ]
    return ComparisonSummary(
        keys,
        len(added_keys),
        len(removed_keys),
        len(changed),
        _examples(after_rows.loc[added_keys], keys),
        _examples(before_rows.loc[removed_keys], keys),
        _changed_examples(before_rows, after_rows, changed, keys, comparable),
    )


def _compare_complete_rows(
    before: pd.DataFrame, after: pd.DataFrame
) -> ComparisonSummary:
    before_records = {tuple(row) for row in before.itertuples(index=False, name=None)}
    after_records = {tuple(row) for row in after.itertuples(index=False, name=None)}
    added = after_records - before_records
    removed = before_records - after_records
    return ComparisonSummary(
        (),
        len(added),
        len(removed),
        0,
        _record_examples(added, after.columns),
        _record_examples(removed, before.columns),
        (),
    )


def _examples(frame: pd.DataFrame, keys: tuple[str, ...]) -> tuple[dict[str, Any], ...]:
    if frame.empty:
        return ()
    return tuple(_record_examples(frame.reset_index(drop=True).head(5), frame.columns))


def _changed_examples(
    before: pd.DataFrame,
    after: pd.DataFrame,
    changed: list[Any],
    keys: tuple[str, ...],
    columns: list[str],
) -> tuple[dict[str, Any], ...]:
    examples = []
    for key in changed[:5]:
        differences = {
            column: {
                "before": _json_value(before.loc[key, column]),
                "after": _json_value(after.loc[key, column]),
            }
            for column in columns
            if not _values_equal(before.loc[key, column], after.loc[key, column])
        }
        examples.append({"key": _json_value(key), "changes": differences})
    return tuple(examples)


def _record_examples(records: Any, columns: Any) -> tuple[dict[str, Any], ...]:
    if isinstance(records, pd.DataFrame):
        rows = records.itertuples(index=False, name=None)
    else:
        rows = records
    return tuple(
        {str(column): _json_value(value) for column, value in zip(columns, row)}
        for row in list(rows)[:5]
    )


def _json_value(value: Any) -> Any:
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, (pd.Timestamp, pd.Timedelta)):
        return str(value)
    return value


def _values_equal(left: Any, right: Any) -> bool:
    if pd.isna(left) and pd.isna(right):
        return True
    return bool(left == right)
