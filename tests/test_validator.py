from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from datake.config import load_settings
from datake.validator import validate_dataframe


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
    }
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    path = config_dir / "settings.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "data" / "input").mkdir(parents=True)
    return path


def _issues_by_check(summary) -> dict[str, list]:
    grouped: dict[str, list] = {}
    for issue in summary.issues:
        grouped.setdefault(issue.check, []).append(issue)
    return grouped


def test_clean_dataframe_passes(tmp_path: Path) -> None:
    settings = load_settings(write_settings(tmp_path))
    dataframe = pd.DataFrame(
        {
            "customer_id": [1, 2],
            "email": ["ada@example.com", "alan@example.com"],
            "signup_date": ["2024-01-15", "2024-02-01"],
            "amount": [10.5, 20],
        }
    )

    summary = validate_dataframe(dataframe, settings)

    assert summary.passed
    assert summary.error_count == 0
    assert summary.issues == []


def test_missing_values_on_required_column_are_errors(tmp_path: Path) -> None:
    settings = load_settings(write_settings(tmp_path))
    dataframe = pd.DataFrame(
        {
            "customer_id": [1, None],
            "email": ["ada@example.com", "alan@example.com"],
            "signup_date": ["2024-01-15", "2024-02-01"],
            "amount": [10, 20],
        }
    )

    summary = validate_dataframe(dataframe, settings)
    missing = _issues_by_check(summary)["missing_value"]

    assert not summary.passed
    assert missing[0].column == "customer_id"
    assert missing[0].severity == "error"
    assert missing[0].row_count == 1


def test_duplicate_rows_and_unique_ids(tmp_path: Path) -> None:
    settings = load_settings(write_settings(tmp_path))
    row = {
        "customer_id": 1,
        "email": "ada@example.com",
        "signup_date": "2024-01-15",
        "amount": 10,
    }
    dataframe = pd.DataFrame([row, row])

    summary = validate_dataframe(dataframe, settings)
    grouped = _issues_by_check(summary)

    assert any(issue.row_count == 1 for issue in grouped["duplicate_row"])
    assert any(issue.column == "customer_id" for issue in grouped["business_rule"])


def test_inconsistent_column_names(tmp_path: Path) -> None:
    settings = load_settings(write_settings(tmp_path))
    dataframe = pd.DataFrame(
        {
            "customer_id": [1],
            "Customer Name": ["Ada"],
            "email": ["ada@example.com"],
            "signup_date": ["2024-01-15"],
            "amount": [10],
        }
    )

    summary = validate_dataframe(dataframe, settings)
    column_issues = _issues_by_check(summary)["inconsistent_column"]

    assert summary.passed
    assert any(issue.column == "Customer Name" for issue in column_issues)


def test_invalid_dates_and_types(tmp_path: Path) -> None:
    settings = load_settings(write_settings(tmp_path))
    dataframe = pd.DataFrame(
        {
            "customer_id": [1, 2],
            "email": ["ada@example.com", "alan@example.com"],
            "signup_date": ["2024-01-15", "not-a-date"],
            "amount": [10, "abc"],
        }
    )

    summary = validate_dataframe(dataframe, settings)
    grouped = _issues_by_check(summary)

    assert grouped["invalid_date"][0].row_count == 1
    assert grouped["invalid_type"][0].row_count == 1


def test_business_rules_email_and_min_amount(tmp_path: Path) -> None:
    settings = load_settings(write_settings(tmp_path))
    dataframe = pd.DataFrame(
        {
            "customer_id": [1, 2],
            "email": ["ada@example.com", "not-an-email"],
            "signup_date": ["2024-01-15", "2024-02-01"],
            "amount": [10, -5],
        }
    )

    summary = validate_dataframe(dataframe, settings)
    business = _issues_by_check(summary)["business_rule"]

    assert any(issue.column == "email" for issue in business)
    assert any(issue.column == "amount" for issue in business)


def test_missing_required_column(tmp_path: Path) -> None:
    settings = load_settings(write_settings(tmp_path))
    dataframe = pd.DataFrame(
        {
            "customer_id": [1],
            "signup_date": ["2024-01-15"],
            "amount": [10],
        }
    )

    summary = validate_dataframe(dataframe, settings)

    assert not summary.passed
    assert any(
        issue.column == "email" and issue.check == "business_rule"
        for issue in summary.issues
    )


def test_validation_does_not_mutate_dataframe(tmp_path: Path) -> None:
    settings = load_settings(write_settings(tmp_path))
    dataframe = pd.DataFrame(
        {
            "customer_id": [1],
            "email": ["ada@example.com"],
            "signup_date": ["2024-01-15"],
            "amount": [10],
        }
    )
    original = dataframe.copy()

    validate_dataframe(dataframe, settings)

    pd.testing.assert_frame_equal(dataframe, original)


def test_named_profile_overrides_base_rules(tmp_path: Path) -> None:
    config_path = write_settings(tmp_path)
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    raw["profiles"] = {
        "lenient": {
            "validation": {
                "required_columns": ["customer_id"],
                "email_columns": [],
            },
            "cleaning": {"drop_if_missing": ["customer_id"]},
        }
    }
    config_path.write_text(json.dumps(raw), encoding="utf-8")

    settings = load_settings(config_path, profile="lenient")
    summary = validate_dataframe(pd.DataFrame({"customer_id": [1]}), settings)

    assert settings.profile_name == "lenient"
    assert settings.available_profiles == ("lenient",)
    assert summary.passed
