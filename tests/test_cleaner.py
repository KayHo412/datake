from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from datake.cleaner import clean_dataframe, standardize_column_name
from datake.config import load_settings


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
            "fill_values": {"customer_name": "Unknown", "amount": 0},
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


def test_standardize_column_name() -> None:
    aliases = {"Customer Name": "customer_name"}
    assert standardize_column_name("Customer Name", aliases) == "customer_name"
    assert standardize_column_name(" Sign Up Date ", {}) == "sign_up_date"


def test_clean_renames_and_drops_bad_rows(tmp_path: Path) -> None:
    settings = load_settings(write_settings(tmp_path))
    dataframe = pd.DataFrame(
        {
            "customer_id": [1, 2, 2, 3, None],
            "Customer Name": ["Ada", "Alan", "Alan", "Grace", "Kay"],
            "email": [
                "ada@example.com",
                "not-an-email",
                "not-an-email",
                "grace@example.com",
                "kay@example.com",
            ],
            "signup_date": [
                "2024-01-15",
                "2024-02-01",
                "2024-02-01",
                "not-a-date",
                "2024-04-01",
            ],
            "amount": [100.5, 200, 200, -15, 50],
        }
    )
    original = dataframe.copy()

    result = clean_dataframe(dataframe, settings)

    pd.testing.assert_frame_equal(dataframe, original)
    assert "customer_name" in result.column_names
    assert "Customer Name" not in result.column_names
    assert list(result.dataframe["customer_id"]) == [1]
    assert result.rows_out < result.rows_in
    assert any("Renamed columns" in action for action in result.actions)
    assert any("invalid email" in action for action in result.actions)
    assert any("invalid dates" in action for action in result.actions)
    assert any("missing required" in action for action in result.actions)


def test_fill_missing_and_clamp_amount(tmp_path: Path) -> None:
    settings = load_settings(write_settings(tmp_path))
    dataframe = pd.DataFrame(
        {
            "customer_id": [1, 2],
            "Customer Name": [None, "Alan"],
            "email": ["ada@example.com", "alan@example.com"],
            "signup_date": ["2024-01-15", "2024-02-01"],
            "amount": [None, -5],
        }
    )

    result = clean_dataframe(dataframe, settings)

    assert list(result.dataframe["customer_name"]) == ["Unknown", "Alan"]
    assert list(result.dataframe["amount"]) == [0, 0]
    assert any("Filled" in action for action in result.actions)
    assert any("Clamped" in action for action in result.actions)


def test_drop_duplicates_keeps_first(tmp_path: Path) -> None:
    settings = load_settings(write_settings(tmp_path))
    dataframe = pd.DataFrame(
        {
            "customer_id": [1, 1],
            "email": ["ada@example.com", "ada@example.com"],
            "signup_date": ["2024-01-15", "2024-01-16"],
            "amount": [10, 99],
        }
    )

    result = clean_dataframe(dataframe, settings)

    assert result.rows_out == 1
    assert result.dataframe.iloc[0]["amount"] == 10
