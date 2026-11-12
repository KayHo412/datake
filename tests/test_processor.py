from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from datake.config import load_settings
from datake.processor import (
    IncompatibleDatasetsError,
    merge_dataframes,
    process_and_merge,
    process_file,
)


def write_settings(tmp_path: Path) -> Path:
    payload = {
        "paths": {
            "input_dir": "data/input",
            "processed_dir": "data/processed",
            "reports_dir": "data/reports",
            "log_file": "logs/datake.log",
        },
        "files": {"supported_extensions": [".csv"]},
        "csv": {"encodings": ["utf-8"], "delimiter": None},
        "logging": {"level": "INFO"},
        "validation": {
            "required_columns": ["customer_id", "email"],
            "date_columns": ["signup_date"],
            "numeric_columns": ["amount"],
            "unique_columns": ["customer_id"],
            "email_columns": ["email"],
            "numeric_constraints": {"amount": {"min": 0}},
            "max_examples": 5,
        },
        "cleaning": {
            "standardize_column_names": True,
            "column_aliases": {"Customer Name": "customer_name"},
            "fill_values": {"customer_name": "Unknown"},
            "drop_if_missing": ["customer_id", "email"],
            "drop_duplicates": True,
            "duplicate_subset": ["customer_id"],
            "duplicate_keep": "first",
            "date_format": "%Y-%m-%d",
            "drop_invalid_dates": True,
            "coerce_numeric": True,
            "drop_invalid_numeric": True,
            "clamp_numeric": True,
            "drop_invalid_emails": True,
        },
    }
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    path = config_dir / "settings.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "data" / "input").mkdir(parents=True)
    (tmp_path / "data" / "processed").mkdir(parents=True)
    return path


def test_process_file_writes_cleaned_copy_and_keeps_original(tmp_path: Path) -> None:
    settings = load_settings(write_settings(tmp_path))
    source = settings.input_dir / "customers.csv"
    original = (
        "customer_id,Customer Name,email,signup_date,amount\n"
        "1,Ada,ada@example.com,2024-01-15,10\n"
    )
    source.write_text(original, encoding="utf-8")

    result = process_file(source, settings)

    assert result.succeeded
    assert source.read_text(encoding="utf-8") == original
    assert result.output_path is not None
    assert result.output_path.parent == settings.processed_dir
    assert result.output_path.name == "customers_cleaned.csv"
    assert result.output_path.is_file()
    written = result.output_path.read_text(encoding="utf-8")
    assert "customer_name" in written
    assert "Customer Name" not in written.splitlines()[0]


def test_process_file_skips_unreadable_without_raising(tmp_path: Path) -> None:
    settings = load_settings(write_settings(tmp_path))
    result = process_file(settings.input_dir / "missing.csv", settings)

    assert not result.succeeded
    assert result.error is not None
    assert not list(settings.processed_dir.glob("*.csv"))


def test_merge_compatible_and_reject_incompatible() -> None:
    left = pd.DataFrame({"customer_id": [1], "email": ["a@b.com"]})
    right = pd.DataFrame({"email": ["c@d.com"], "customer_id": [2]})
    merged = merge_dataframes([left, right])
    assert list(merged.columns) == ["customer_id", "email"]
    assert len(merged) == 2

    other = pd.DataFrame({"order_id": [9]})
    with pytest.raises(IncompatibleDatasetsError):
        merge_dataframes([left, other])


def test_process_and_merge_writes_merged_csv(tmp_path: Path) -> None:
    settings = load_settings(write_settings(tmp_path))
    first = settings.input_dir / "a.csv"
    second = settings.input_dir / "b.csv"
    first.write_text(
        "customer_id,Customer Name,email,signup_date,amount\n"
        "1,Ada,ada@example.com,2024-01-15,10\n",
        encoding="utf-8",
    )
    second.write_text(
        "customer_id,Customer Name,email,signup_date,amount\n"
        "2,Alan,alan@example.com,2024-02-01,20\n",
        encoding="utf-8",
    )

    results, merged_path, merged = process_and_merge([first, second], settings)

    assert all(result.succeeded for result in results)
    assert merged_path == settings.processed_dir / "merged.csv"
    assert merged is not None
    assert len(merged) == 2
    assert merged_path.is_file()
    assert first.read_text(encoding="utf-8").startswith("customer_id,Customer Name")


@pytest.mark.parametrize(
    ("output_format", "expected_suffix"),
    [("json", ".json"), ("jsonl", ".jsonl"), ("parquet", ".parquet")],
)
def test_process_file_writes_configured_output_format(
    tmp_path: Path,
    output_format: str,
    expected_suffix: str,
) -> None:
    config_path = write_settings(tmp_path)
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    raw["files"]["output_format"] = output_format
    config_path.write_text(json.dumps(raw), encoding="utf-8")
    settings = load_settings(config_path)
    source = settings.input_dir / "customers.csv"
    source.write_text("customer_id,email\n1,ada@example.com\n", encoding="utf-8")

    result = process_file(source, settings)

    assert result.succeeded
    assert result.output_path is not None
    assert result.output_path.suffix == expected_suffix
    assert result.output_path.is_file()
    if output_format == "parquet":
        round_trip = pd.read_parquet(result.output_path)
    else:
        round_trip = pd.read_json(
            result.output_path,
            lines=output_format == "jsonl",
        )
    assert round_trip.to_dict("records") == [
        {"customer_id": 1, "email": "ada@example.com"}
    ]
