from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from datake.config import load_settings
from datake.file_reader import list_input_files, read_file


def write_settings(tmp_path: Path, **overrides: object) -> Path:
    payload = {
        "paths": {
            "input_dir": "data/input",
            "processed_dir": "data/processed",
            "reports_dir": "data/reports",
            "log_file": "logs/datake.log",
        },
        "files": {"supported_extensions": [".csv"]},
        "csv": {"encodings": ["utf-8", "utf-8-sig", "latin-1"], "delimiter": None},
        "logging": {"level": "INFO"},
    }
    payload.update(overrides)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    path = config_dir / "settings.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "data" / "input").mkdir(parents=True)
    return path


def test_read_valid_csv(tmp_path: Path) -> None:
    config_path = write_settings(tmp_path)
    settings = load_settings(config_path)
    csv_path = tmp_path / "customers.csv"
    csv_path.write_text(
        "customer_id,name,amount\n1,Ada,10.5\n2,Alan,20\n",
        encoding="utf-8",
    )

    result = read_file(csv_path, settings)

    assert result.succeeded
    assert result.row_count == 2
    assert result.column_names == ["customer_id", "name", "amount"]
    assert result.dataframe is not None
    assert list(result.dataframe["name"]) == ["Ada", "Alan"]
    assert csv_path.read_text(encoding="utf-8").startswith("customer_id")


def test_read_valid_excel_workbook(tmp_path: Path) -> None:
    config_path = write_settings(
        tmp_path,
        files={"supported_extensions": [".xlsx"]},
    )
    settings = load_settings(config_path)
    excel_path = tmp_path / "customers.xlsx"
    pd.DataFrame(
        {"customer_id": [1, 2], "name": ["Ada", "Alan"]}
    ).to_excel(excel_path, index=False)

    result = read_file(excel_path, settings)

    assert result.succeeded
    assert result.row_count == 2
    assert result.column_names == ["customer_id", "name"]
    assert result.dataframe is not None
    assert list(result.dataframe["name"]) == ["Ada", "Alan"]


@pytest.mark.parametrize(
    ("extension", "content"),
    [
        (".json", '[{"id": 1, "name": "Ada"}]'),
        (".jsonl", '{"id": 1, "name": "Ada"}\n'),
    ],
)
def test_read_json_formats(tmp_path: Path, extension: str, content: str) -> None:
    config_path = write_settings(
        tmp_path,
        files={"supported_extensions": [extension]},
    )
    settings = load_settings(config_path)
    source = tmp_path / f"customers{extension}"
    source.write_text(content, encoding="utf-8")

    result = read_file(source, settings)

    assert result.succeeded
    assert result.dataframe is not None
    assert result.dataframe.to_dict("records") == [{"id": 1, "name": "Ada"}]


def test_read_parquet(tmp_path: Path) -> None:
    config_path = write_settings(
        tmp_path,
        files={"supported_extensions": [".parquet"]},
    )
    settings = load_settings(config_path)
    source = tmp_path / "customers.parquet"
    pd.DataFrame({"id": [1], "name": ["Ada"]}).to_parquet(source, index=False)

    result = read_file(source, settings)

    assert result.succeeded
    assert result.dataframe is not None
    assert result.dataframe.to_dict("records") == [{"id": 1, "name": "Ada"}]


def test_missing_file_returns_failure(tmp_path: Path) -> None:
    settings = load_settings(write_settings(tmp_path))
    result = read_file(tmp_path / "missing.csv", settings)

    assert not result.succeeded
    assert result.dataframe is None
    assert result.error is not None
    assert "not found" in result.error.lower()


def test_empty_csv_returns_failure(tmp_path: Path) -> None:
    settings = load_settings(write_settings(tmp_path))
    csv_path = tmp_path / "empty.csv"
    csv_path.write_text("", encoding="utf-8")

    result = read_file(csv_path, settings)

    assert not result.succeeded
    assert result.error is not None


def test_corrupted_csv_returns_failure(tmp_path: Path) -> None:
    settings = load_settings(write_settings(tmp_path))
    csv_path = tmp_path / "broken.csv"
    csv_path.write_text('name,age\n"unclosed quote,12\n', encoding="utf-8")

    result = read_file(csv_path, settings)

    assert not result.succeeded
    assert result.dataframe is None
    assert result.error is not None


def test_unsupported_extension(tmp_path: Path) -> None:
    settings = load_settings(write_settings(tmp_path))
    other = tmp_path / "notes.txt"
    other.write_text("hello", encoding="utf-8")

    result = read_file(other, settings)

    assert not result.succeeded
    assert "Unsupported file type" in (result.error or "")


def test_latin1_fallback_encoding(tmp_path: Path) -> None:
    settings = load_settings(write_settings(tmp_path))
    csv_path = tmp_path / "latin.csv"
    csv_path.write_bytes("name,city\nJosé,Sao Paulo\n".encode("latin-1"))

    result = read_file(csv_path, settings)

    assert result.succeeded
    assert result.dataframe is not None
    assert result.dataframe.loc[0, "name"] == "José"


def test_list_input_files_ignores_unsupported_types(tmp_path: Path) -> None:
    settings = load_settings(write_settings(tmp_path))
    (settings.input_dir / "a.csv").write_text("id\n1\n", encoding="utf-8")
    (settings.input_dir / "ignore.txt").write_text("nope", encoding="utf-8")

    files = list_input_files(settings)

    assert [path.name for path in files] == ["a.csv"]


def test_read_does_not_require_pandas_engine_guess_when_delimiter_set(
    tmp_path: Path,
) -> None:
    config_path = write_settings(
        tmp_path,
        csv={"encodings": ["utf-8"], "delimiter": ";"},
    )
    settings = load_settings(config_path)
    csv_path = tmp_path / "semi.csv"
    csv_path.write_text("id;name\n1;Ada\n", encoding="utf-8")

    result = read_file(csv_path, settings)

    assert result.succeeded
    assert result.column_names == ["id", "name"]
