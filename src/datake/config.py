"""Load application settings from JSON.

Configuration lives outside the code so paths, encodings, and later
business rules can change without editing Python modules.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConfigError(Exception):
    """Raised when settings cannot be found or parsed."""


@dataclass(frozen=True)
class ValidationSettings:
    """Configurable quality checks applied after a file is read."""

    required_columns: tuple[str, ...]
    date_columns: tuple[str, ...]
    numeric_columns: tuple[str, ...]
    unique_columns: tuple[str, ...]
    email_columns: tuple[str, ...]
    numeric_constraints: dict[str, dict[str, float]]
    max_examples: int


@dataclass(frozen=True)
class CleaningSettings:
    """Configurable transforms applied to a copy of the data."""

    standardize_column_names: bool
    column_aliases: dict[str, str]
    fill_values: dict[str, Any]
    drop_if_missing: tuple[str, ...]
    drop_duplicates: bool
    duplicate_subset: tuple[str, ...]
    duplicate_keep: str
    date_format: str
    drop_invalid_dates: bool
    coerce_numeric: bool
    drop_invalid_numeric: bool
    clamp_numeric: bool
    drop_invalid_emails: bool


@dataclass(frozen=True)
class Settings:
    """Typed view of config/settings.json."""

    project_root: Path
    input_dir: Path
    processed_dir: Path
    reports_dir: Path
    log_file: Path
    supported_extensions: tuple[str, ...]
    csv_encodings: tuple[str, ...]
    csv_delimiter: str | None
    log_level: str
    validation: ValidationSettings
    cleaning: CleaningSettings

    @property
    def config_path(self) -> Path:
        return self.project_root / "config" / "settings.json"


def find_project_root(start: Path | None = None) -> Path:
    """Walk upward from *start* (or the current directory) to find config/."""
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "config" / "settings.json").is_file():
            return candidate
    raise ConfigError(
        "Could not find config/settings.json. Run Datake from the project "
        "directory or pass --config."
    )


def load_settings(config_path: Path | None = None) -> Settings:
    """Read JSON settings and resolve relative paths against the project root."""
    if config_path is None:
        project_root = find_project_root()
        config_path = project_root / "config" / "settings.json"
    else:
        config_path = config_path.resolve()
        if not config_path.is_file():
            raise ConfigError(f"Config file not found: {config_path}")
        project_root = config_path.parent.parent

    try:
        raw: dict[str, Any] = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in {config_path}: {exc}") from exc

    paths = raw.get("paths", {})
    files = raw.get("files", {})
    csv_options = raw.get("csv", {})
    logging_options = raw.get("logging", {})

    def resolve(key: str, default: str) -> Path:
        value = Path(paths.get(key, default))
        return value if value.is_absolute() else project_root / value

    delimiter = csv_options.get("delimiter")
    encodings = csv_options.get("encodings") or ["utf-8"]
    extensions = files.get("supported_extensions") or [".csv"]
    validation_raw = raw.get("validation", {})
    constraints_raw = validation_raw.get("numeric_constraints") or {}
    numeric_constraints = {
        column: {key: float(value) for key, value in bounds.items()}
        for column, bounds in constraints_raw.items()
    }

    return Settings(
        project_root=project_root,
        input_dir=resolve("input_dir", "data/input"),
        processed_dir=resolve("processed_dir", "data/processed"),
        reports_dir=resolve("reports_dir", "data/reports"),
        log_file=resolve("log_file", "logs/datake.log"),
        supported_extensions=tuple(ext.lower() for ext in extensions),
        csv_encodings=tuple(encodings),
        csv_delimiter=str(delimiter) if delimiter else None,
        log_level=str(logging_options.get("level", "INFO")).upper(),
        validation=ValidationSettings(
            required_columns=tuple(validation_raw.get("required_columns") or ()),
            date_columns=tuple(validation_raw.get("date_columns") or ()),
            numeric_columns=tuple(validation_raw.get("numeric_columns") or ()),
            unique_columns=tuple(validation_raw.get("unique_columns") or ()),
            email_columns=tuple(validation_raw.get("email_columns") or ()),
            numeric_constraints=numeric_constraints,
            max_examples=int(validation_raw.get("max_examples") or 5),
        ),
        cleaning=_load_cleaning(raw.get("cleaning", {}), validation_raw),
    )


def _load_cleaning(
    cleaning_raw: dict[str, Any],
    validation_raw: dict[str, Any],
) -> CleaningSettings:
    aliases = {
        str(old): str(new)
        for old, new in (cleaning_raw.get("column_aliases") or {}).items()
    }
    fill_values = dict(cleaning_raw.get("fill_values") or {})
    drop_if_missing = cleaning_raw.get("drop_if_missing")
    if drop_if_missing is None:
        drop_if_missing = validation_raw.get("required_columns") or ()
    subset = cleaning_raw.get("duplicate_subset")
    if subset is None:
        subset = validation_raw.get("unique_columns") or ()

    return CleaningSettings(
        standardize_column_names=bool(
            cleaning_raw.get("standardize_column_names", True)
        ),
        column_aliases=aliases,
        fill_values=fill_values,
        drop_if_missing=tuple(drop_if_missing),
        drop_duplicates=bool(cleaning_raw.get("drop_duplicates", True)),
        duplicate_subset=tuple(subset),
        duplicate_keep=str(cleaning_raw.get("duplicate_keep") or "first"),
        date_format=str(cleaning_raw.get("date_format") or "%Y-%m-%d"),
        drop_invalid_dates=bool(cleaning_raw.get("drop_invalid_dates", True)),
        coerce_numeric=bool(cleaning_raw.get("coerce_numeric", True)),
        drop_invalid_numeric=bool(cleaning_raw.get("drop_invalid_numeric", True)),
        clamp_numeric=bool(cleaning_raw.get("clamp_numeric", True)),
        drop_invalid_emails=bool(cleaning_raw.get("drop_invalid_emails", True)),
    )
