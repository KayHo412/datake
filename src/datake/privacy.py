"""Conservative, name-based privacy metadata for generated reports."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable

import pandas as pd

_PATTERNS = {
    "email": re.compile(r"(^|[_\s-])e?mail($|[_\s-])", re.I),
    "phone": re.compile(r"phone|mobile|telephone", re.I),
    "name": re.compile(r"(^|[_\s-])(first|last|full)?name($|[_\s-])", re.I),
    "address": re.compile(r"address|street|postal|zip", re.I),
}


def detect_sensitive_columns(columns: Iterable[object]) -> dict[str, str]:
    """Classify likely personal-data columns without inspecting cell values."""
    detected: dict[str, str] = {}
    for column in columns:
        name = str(column)
        for category, pattern in _PATTERNS.items():
            if pattern.search(name):
                detected[name] = category
                break
    return detected


def hash_sensitive_columns(
    dataframe: pd.DataFrame,
    columns: Iterable[str],
) -> pd.DataFrame:
    """Return a copy with selected values replaced by stable SHA-256 hashes."""
    result = dataframe.copy()
    for column in columns:
        if column in result.columns:
            result[column] = result[column].map(
                lambda value: hashlib.sha256(str(value).encode("utf-8")).hexdigest()
            )
    return result
