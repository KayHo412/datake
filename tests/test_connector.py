from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from datake.config import load_settings
from datake.connector import ConnectorError, fetch_csv, fetch_json, fetch_sqlite


def write_settings(tmp_path: Path, **connector_options: object) -> Path:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    payload = {
        "paths": {"input_dir": "data/input"},
        "files": {"supported_extensions": [".json"]},
        "connectors": connector_options,
    }
    path = config_dir / "settings.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class FakeResponse:
    def __init__(self, body: bytes, content_type: str = "application/json"):
        self.body = body
        self.position = 0
        self.headers = SimpleNamespace(get_content_type=lambda: content_type)

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, size: int) -> bytes:
        chunk = self.body[self.position : self.position + size]
        self.position += len(chunk)
        return chunk


def test_fetch_json_saves_records(monkeypatch, tmp_path: Path) -> None:
    settings = load_settings(
        write_settings(tmp_path, allowed_hosts=["api.example.com"])
    )
    response = FakeResponse(b'{"results": [{"id": 1, "name": "Ada"}]}')
    monkeypatch.setattr("datake.connector.urlopen", lambda *args, **kwargs: response)

    destination = fetch_json(
        "https://api.example.com/customers",
        tmp_path / "data" / "input" / "customers.json",
        settings,
    )

    assert json.loads(destination.read_text(encoding="utf-8")) == [
        {"id": 1, "name": "Ada"}
    ]


def test_fetch_json_rejects_unapproved_host(tmp_path: Path) -> None:
    settings = load_settings(
        write_settings(tmp_path, allowed_hosts=["api.example.com"])
    )

    with pytest.raises(ConnectorError, match="not approved"):
        fetch_json("https://other.example.com/data", tmp_path / "data.json", settings)


def test_fetch_json_rejects_oversized_response(monkeypatch, tmp_path: Path) -> None:
    settings = load_settings(write_settings(tmp_path, max_response_bytes=4))
    response = FakeResponse(b'[{"id": 1}]')
    monkeypatch.setattr("datake.connector.urlopen", lambda *args, **kwargs: response)

    with pytest.raises(ConnectorError, match="exceeds"):
        fetch_json("https://api.example.com/data", tmp_path / "data.json", settings)


def test_fetch_csv_saves_published_sheet_data(monkeypatch, tmp_path: Path) -> None:
    settings = load_settings(
        write_settings(tmp_path, allowed_hosts=["docs.google.com"])
    )
    response = FakeResponse(b"id,name\n1,Ada\n", "text/csv")
    monkeypatch.setattr("datake.connector.urlopen", lambda *args, **kwargs: response)

    destination = fetch_csv(
        "https://docs.google.com/spreadsheets/d/id/export?format=csv",
        tmp_path / "data.csv",
        settings,
    )

    assert destination.read_text(encoding="utf-8") == "id,name\n1,Ada\n"


def test_fetch_sqlite_writes_query_result(tmp_path: Path) -> None:
    database = tmp_path / "source.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE customers (id INTEGER, name TEXT)")
        connection.execute("INSERT INTO customers VALUES (1, 'Ada')")

    destination = fetch_sqlite(
        database,
        "SELECT * FROM customers",
        tmp_path / "customers.csv",
    )

    assert destination.read_text(encoding="utf-8") == "id,name\n1,Ada\n"
