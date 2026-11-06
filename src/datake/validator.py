"""Inspect a DataFrame for quality issues without changing it.

Phase 2 reports problems. Cleaning belongs in a later phase.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from datake.config import Settings, ValidationSettings

logger = logging.getLogger(__name__)

SNAKE_CASE = re.compile(r"^[a-z][a-z0-9_]*$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass
class ValidationIssue:
    """One kind of problem found in the dataset."""

    check: str
    severity: str
    message: str
    column: str | None = None
    row_count: int = 0
    examples: list[str] = field(default_factory=list)


@dataclass
class ValidationSummary:
    """Full validation report for one file."""

    source_path: Path
    row_count: int
    column_names: list[str]
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "warning")

    @property
    def passed(self) -> bool:
        """True when no error-level issues were found. Warnings still pass."""
        return self.error_count == 0


def validate_dataframe(
    dataframe: pd.DataFrame,
    settings: Settings,
    source_path: Path | None = None,
) -> ValidationSummary:
    """Run configured checks and return a summary.

    The DataFrame is not modified. Callers still own the original file on disk.
    """
    rules = settings.validation
    path = source_path or Path("<memory>")
    summary = ValidationSummary(
        source_path=path,
        row_count=len(dataframe),
        column_names=[str(column) for column in dataframe.columns],
    )

    _check_column_names(dataframe, summary, rules)
    _check_required_columns(dataframe, summary, rules)
    _check_missing_values(dataframe, summary, rules)
    _check_duplicate_rows(dataframe, summary, rules)
    _check_unique_columns(dataframe, summary, rules)
    _check_dates(dataframe, summary, rules)
    _check_numeric_types(dataframe, summary, rules)
    _check_numeric_bounds(dataframe, summary, rules)
    _check_emails(dataframe, summary, rules)

    logger.info(
        "Validated %s: %s errors, %s warnings",
        path.name,
        summary.error_count,
        summary.warning_count,
    )
    return summary


def _check_column_names(
    dataframe: pd.DataFrame,
    summary: ValidationSummary,
    rules: ValidationSettings,
) -> None:
    names = [str(column) for column in dataframe.columns]
    seen: dict[str, int] = {}
    for name in names:
        seen[name] = seen.get(name, 0) + 1
        if name != name.strip():
            summary.issues.append(
                ValidationIssue(
                    check="inconsistent_column",
                    severity="warning",
                    message=f"Column name has leading or trailing whitespace: {name!r}",
                    column=name,
                )
            )
        elif " " in name or not SNAKE_CASE.match(name):
            summary.issues.append(
                ValidationIssue(
                    check="inconsistent_column",
                    severity="warning",
                    message=(
                        f"Column {name!r} is not snake_case "
                        "(expected lowercase letters, digits, underscores)"
                    ),
                    column=name,
                )
            )

    for name, count in seen.items():
        if count > 1:
            summary.issues.append(
                ValidationIssue(
                    check="inconsistent_column",
                    severity="error",
                    message=f"Duplicate column name {name!r} appears {count} times",
                    column=name,
                    row_count=count,
                )
            )


def _check_required_columns(
    dataframe: pd.DataFrame,
    summary: ValidationSummary,
    rules: ValidationSettings,
) -> None:
    present = set(dataframe.columns)
    for column in rules.required_columns:
        if column not in present:
            summary.issues.append(
                ValidationIssue(
                    check="business_rule",
                    severity="error",
                    message=f"Required column {column!r} is missing",
                    column=column,
                )
            )


def missing_mask(series: pd.Series) -> pd.Series:
    """True for NaN, blank strings, and common null placeholders."""
    missing = series.isna()
    if series.dtype == object or str(series.dtype) == "string":
        text = series.astype("string").str.strip()
        missing = missing | text.isna() | text.eq("") | text.str.lower().isin(
            ["nan", "none", "null"]
        )
    return missing


def _check_missing_values(
    dataframe: pd.DataFrame,
    summary: ValidationSummary,
    rules: ValidationSettings,
) -> None:
    for column in dataframe.columns:
        mask = missing_mask(dataframe[column])
        count = int(mask.sum())
        if count == 0:
            continue
        severity = "error" if column in rules.required_columns else "warning"
        examples = _examples(dataframe.index[mask], rules.max_examples)
        summary.issues.append(
            ValidationIssue(
                check="missing_value",
                severity=severity,
                message=f"Column {column!r} has {count} missing value(s)",
                column=str(column),
                row_count=count,
                examples=examples,
            )
        )


def _check_duplicate_rows(
    dataframe: pd.DataFrame,
    summary: ValidationSummary,
    rules: ValidationSettings,
) -> None:
    duplicated = dataframe.duplicated(keep="first")
    count = int(duplicated.sum())
    if count == 0:
        return
    summary.issues.append(
        ValidationIssue(
            check="duplicate_row",
            severity="warning",
            message=f"Found {count} duplicate row(s) (exact copies of earlier rows)",
            row_count=count,
            examples=_examples(dataframe.index[duplicated], rules.max_examples),
        )
    )


def _check_unique_columns(
    dataframe: pd.DataFrame,
    summary: ValidationSummary,
    rules: ValidationSettings,
) -> None:
    for column in rules.unique_columns:
        if column not in dataframe.columns:
            continue
        duplicated = dataframe.duplicated(subset=[column], keep="first")
        present = ~missing_mask(dataframe[column])
        mask = duplicated & present
        count = int(mask.sum())
        if count == 0:
            continue
        summary.issues.append(
            ValidationIssue(
                check="business_rule",
                severity="error",
                message=f"Column {column!r} has {count} duplicate value(s)",
                column=column,
                row_count=count,
                examples=_examples(dataframe.index[mask], rules.max_examples),
            )
        )


def _check_dates(
    dataframe: pd.DataFrame,
    summary: ValidationSummary,
    rules: ValidationSettings,
) -> None:
    for column in rules.date_columns:
        if column not in dataframe.columns:
            continue
        series = dataframe[column]
        parsed = pd.to_datetime(series, errors="coerce")
        invalid = parsed.isna() & ~missing_mask(series)
        count = int(invalid.sum())
        if count == 0:
            continue
        summary.issues.append(
            ValidationIssue(
                check="invalid_date",
                severity="error",
                message=f"Column {column!r} has {count} invalid date(s)",
                column=column,
                row_count=count,
                examples=_value_examples(series[invalid], rules.max_examples),
            )
        )


def _check_numeric_types(
    dataframe: pd.DataFrame,
    summary: ValidationSummary,
    rules: ValidationSettings,
) -> None:
    for column in rules.numeric_columns:
        if column not in dataframe.columns:
            continue
        series = dataframe[column]
        parsed = pd.to_numeric(series, errors="coerce")
        invalid = parsed.isna() & ~missing_mask(series)
        count = int(invalid.sum())
        if count == 0:
            continue
        summary.issues.append(
            ValidationIssue(
                check="invalid_type",
                severity="error",
                message=f"Column {column!r} has {count} non-numeric value(s)",
                column=column,
                row_count=count,
                examples=_value_examples(series[invalid], rules.max_examples),
            )
        )


def _check_numeric_bounds(
    dataframe: pd.DataFrame,
    summary: ValidationSummary,
    rules: ValidationSettings,
) -> None:
    for column, bounds in rules.numeric_constraints.items():
        if column not in dataframe.columns:
            continue
        parsed = pd.to_numeric(dataframe[column], errors="coerce")
        mask = pd.Series(False, index=dataframe.index)
        messages: list[str] = []
        if "min" in bounds:
            too_small = parsed.notna() & (parsed < bounds["min"])
            mask = mask | too_small
            messages.append(f"min {bounds['min']}")
        if "max" in bounds:
            too_large = parsed.notna() & (parsed > bounds["max"])
            mask = mask | too_large
            messages.append(f"max {bounds['max']}")
        count = int(mask.sum())
        if count == 0:
            continue
        summary.issues.append(
            ValidationIssue(
                check="business_rule",
                severity="error",
                message=(
                    f"Column {column!r} has {count} value(s) outside "
                    f"configured bounds ({', '.join(messages)})"
                ),
                column=column,
                row_count=count,
                examples=_value_examples(dataframe[column][mask], rules.max_examples),
            )
        )


def _check_emails(
    dataframe: pd.DataFrame,
    summary: ValidationSummary,
    rules: ValidationSettings,
) -> None:
    for column in rules.email_columns:
        if column not in dataframe.columns:
            continue
        series = dataframe[column]
        present = ~missing_mask(series)
        text = series.astype("string").str.strip()
        invalid = present & ~text.str.match(EMAIL_PATTERN.pattern, na=False)
        count = int(invalid.sum())
        if count == 0:
            continue
        summary.issues.append(
            ValidationIssue(
                check="business_rule",
                severity="error",
                message=f"Column {column!r} has {count} invalid email(s)",
                column=column,
                row_count=count,
                examples=_value_examples(series[invalid], rules.max_examples),
            )
        )


def _examples(index: pd.Index, limit: int) -> list[str]:
    return [f"row {int(i)}" for i in list(index)[:limit]]


def _value_examples(series: pd.Series, limit: int) -> list[str]:
    values = []
    for index, value in series.head(limit).items():
        values.append(f"row {int(index)}={value!r}")
    return values
