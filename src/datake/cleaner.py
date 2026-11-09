"""Transform a DataFrame copy using configured cleaning rules.

Original files on disk are never touched. Every drop or fill is recorded
in ``CleanResult.actions`` so data is not discarded silently.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

import pandas as pd

from datake.config import Settings
from datake.validator import EMAIL_PATTERN, missing_mask

logger = logging.getLogger(__name__)

NON_WORD = re.compile(r"[^\w]+", flags=re.UNICODE)
MULTI_UNDERSCORE = re.compile(r"_+")


@dataclass
class CleanResult:
    """Cleaned table plus an audit trail of what changed."""

    dataframe: pd.DataFrame
    rows_in: int
    rows_out: int
    column_names: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    rejected_dataframe: pd.DataFrame = field(default_factory=pd.DataFrame)


def clean_dataframe(dataframe: pd.DataFrame, settings: Settings) -> CleanResult:
    """Return a cleaned copy of *dataframe* according to ``settings.cleaning``."""
    working = dataframe.copy()
    actions: list[str] = []
    rejected: list[pd.DataFrame] = []
    rows_in = len(working)
    rules = settings.cleaning

    _blank_strings_to_na(working)

    if rules.standardize_column_names or rules.column_aliases:
        working = _standardize_columns(working, settings, actions)

    if rules.coerce_numeric:
        working = _coerce_numeric(working, settings, actions, rejected)
    working = _normalize_dates(working, settings, actions, rejected)

    if rules.drop_invalid_emails:
        working = _drop_invalid_emails(working, settings, actions, rejected)

    _fill_missing(working, settings, actions)
    working = _drop_missing_required(working, settings, actions, rejected)

    if rules.drop_duplicates:
        working = _drop_duplicates(working, settings, actions, rejected)

    _downcast_whole_numbers(working, settings)
    working = working.reset_index(drop=True)
    result = CleanResult(
        dataframe=working,
        rows_in=rows_in,
        rows_out=len(working),
        column_names=[str(column) for column in working.columns],
        actions=actions,
        rejected_dataframe=(
            pd.concat(rejected, ignore_index=True)
            if rejected
            else pd.DataFrame(columns=[*working.columns, "rejection_reason"])
        ),
    )
    logger.info(
        "Cleaned dataset: %s rows in, %s rows out, %s actions",
        result.rows_in,
        result.rows_out,
        len(actions),
    )
    return result


def standardize_column_name(name: str, aliases: dict[str, str]) -> str:
    """Map a header to snake_case, honoring explicit aliases first."""
    stripped = str(name).strip()
    if name in aliases:
        return aliases[str(name)]
    if stripped in aliases:
        return aliases[stripped]

    text = stripped.lower().replace(" ", "_")
    text = NON_WORD.sub("_", text)
    text = MULTI_UNDERSCORE.sub("_", text).strip("_")
    if text and text[0].isdigit():
        text = f"col_{text}"
    return text or "unnamed"


def _blank_strings_to_na(dataframe: pd.DataFrame) -> None:
    for column in dataframe.columns:
        series = dataframe[column]
        if series.dtype == object or str(series.dtype) == "string":
            mask = missing_mask(series)
            dataframe.loc[mask, column] = pd.NA


def _standardize_columns(
    dataframe: pd.DataFrame,
    settings: Settings,
    actions: list[str],
) -> pd.DataFrame:
    aliases = settings.cleaning.column_aliases
    new_names: list[str] = []
    used: dict[str, int] = {}
    renamed: list[str] = []

    for original in dataframe.columns:
        candidate = standardize_column_name(str(original), aliases)
        count = used.get(candidate, 0) + 1
        used[candidate] = count
        final = candidate if count == 1 else f"{candidate}_{count}"
        new_names.append(final)
        if final != str(original):
            renamed.append(f"{original!r} -> {final!r}")

    dataframe.columns = new_names
    if renamed:
        actions.append("Renamed columns: " + "; ".join(renamed))
    return dataframe


def _without_rows(
    dataframe: pd.DataFrame,
    mask: pd.Series,
    rejected: list[pd.DataFrame],
    reason: str,
) -> pd.DataFrame:
    if not bool(mask.any()):
        return dataframe
    removed = dataframe.loc[mask].copy()
    removed["rejection_reason"] = reason
    rejected.append(removed)
    return dataframe.loc[~mask].copy()


def _coerce_numeric(
    dataframe: pd.DataFrame,
    settings: Settings,
    actions: list[str],
    rejected: list[pd.DataFrame],
) -> pd.DataFrame:
    rules = settings.cleaning
    constraints = settings.validation.numeric_constraints
    for column in settings.validation.numeric_columns:
        if column not in dataframe.columns:
            continue
        parsed = pd.to_numeric(dataframe[column], errors="coerce")
        invalid = parsed.isna() & ~missing_mask(dataframe[column])
        invalid_count = int(invalid.sum())
        if rules.drop_invalid_numeric and invalid_count:
            dataframe = _without_rows(
                dataframe, invalid, rejected, f"non-numeric {column}"
            )
            parsed = parsed.loc[dataframe.index]
            actions.append(
                f"Dropped {invalid_count} row(s) with non-numeric {column!r}"
            )
        dataframe[column] = parsed
        if rules.clamp_numeric and column in constraints:
            bounds = constraints[column]
            if "min" in bounds:
                below = dataframe[column].notna() & (dataframe[column] < bounds["min"])
                count = int(below.sum())
                if count:
                    dataframe.loc[below, column] = bounds["min"]
                    actions.append(
                        f"Clamped {count} value(s) in {column!r} up to {bounds['min']}"
                    )
            if "max" in bounds:
                above = dataframe[column].notna() & (dataframe[column] > bounds["max"])
                count = int(above.sum())
                if count:
                    dataframe.loc[above, column] = bounds["max"]
                    actions.append(
                        f"Clamped {count} value(s) in {column!r} "
                        f"down to {bounds['max']}"
                    )
    return dataframe


def _normalize_dates(
    dataframe: pd.DataFrame,
    settings: Settings,
    actions: list[str],
    rejected: list[pd.DataFrame],
) -> pd.DataFrame:
    rules = settings.cleaning
    for column in settings.validation.date_columns:
        if column not in dataframe.columns:
            continue
        parsed = pd.to_datetime(dataframe[column], errors="coerce")
        invalid = parsed.isna() & ~missing_mask(dataframe[column])
        invalid_count = int(invalid.sum())
        if rules.drop_invalid_dates and invalid_count:
            dataframe = _without_rows(
                dataframe, invalid, rejected, f"invalid date in {column}"
            )
            parsed = parsed.loc[dataframe.index]
            actions.append(
                f"Dropped {invalid_count} row(s) with invalid dates in {column!r}"
            )
        formatted = parsed.dt.strftime(rules.date_format)
        dataframe = dataframe.copy()
        dataframe[column] = formatted.where(parsed.notna(), pd.NA)
        actions.append(f"Normalized dates in {column!r} to {rules.date_format}")
    return dataframe


def _drop_invalid_emails(
    dataframe: pd.DataFrame,
    settings: Settings,
    actions: list[str],
    rejected: list[pd.DataFrame],
) -> pd.DataFrame:
    for column in settings.validation.email_columns:
        if column not in dataframe.columns:
            continue
        present = ~missing_mask(dataframe[column])
        text = dataframe[column].astype("string").str.strip()
        invalid = present & ~text.str.match(EMAIL_PATTERN.pattern, na=False)
        count = int(invalid.sum())
        if count == 0:
            continue
        dataframe = _without_rows(
            dataframe, invalid, rejected, f"invalid email in {column}"
        )
        actions.append(f"Dropped {count} row(s) with invalid email in {column!r}")
    return dataframe


def _fill_missing(
    dataframe: pd.DataFrame,
    settings: Settings,
    actions: list[str],
) -> None:
    for column, value in settings.cleaning.fill_values.items():
        if column not in dataframe.columns:
            continue
        mask = missing_mask(dataframe[column])
        count = int(mask.sum())
        if count == 0:
            continue
        dataframe.loc[mask, column] = value
        actions.append(f"Filled {count} missing value(s) in {column!r} with {value!r}")


def _drop_missing_required(
    dataframe: pd.DataFrame,
    settings: Settings,
    actions: list[str],
    rejected: list[pd.DataFrame],
) -> pd.DataFrame:
    columns = [
        column
        for column in settings.cleaning.drop_if_missing
        if column in dataframe.columns
    ]
    if not columns:
        return dataframe
    mask = pd.Series(False, index=dataframe.index)
    for column in columns:
        mask = mask | missing_mask(dataframe[column])
    count = int(mask.sum())
    if count == 0:
        return dataframe
    dataframe = _without_rows(
        dataframe, mask, rejected, "missing required column"
    )
    joined = ", ".join(columns)
    actions.append(f"Dropped {count} row(s) missing required column(s): {joined}")
    return dataframe


def _drop_duplicates(
    dataframe: pd.DataFrame,
    settings: Settings,
    actions: list[str],
    rejected: list[pd.DataFrame],
) -> pd.DataFrame:
    subset = [
        column
        for column in settings.cleaning.duplicate_subset
        if column in dataframe.columns
    ] or None
    keep = settings.cleaning.duplicate_keep
    duplicated = dataframe.duplicated(subset=subset, keep=keep)
    count = int(duplicated.sum())
    if count == 0:
        return dataframe
    dataframe = _without_rows(dataframe, duplicated, rejected, "duplicate row")
    target = ", ".join(subset) if subset else "all columns"
    actions.append(f"Dropped {count} duplicate row(s) using {target}")
    return dataframe


def _downcast_whole_numbers(dataframe: pd.DataFrame, settings: Settings) -> None:
    """Keep whole-number IDs as integers after missing values created floats."""
    for column in settings.validation.unique_columns:
        if column not in dataframe.columns:
            continue
        numeric = pd.to_numeric(dataframe[column], errors="coerce")
        if numeric.isna().any():
            continue
        fractional = numeric % 1
        if not bool((fractional == 0).all()):
            continue
        dataframe[column] = numeric.astype("int64")
