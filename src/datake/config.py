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
    )
