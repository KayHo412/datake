from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from datake.config import load_settings
from datake.delivery import DeliveryError, post_json, write_sqlite


def write_settings(tmp_path: Path, **options: object) -> Path:
    config = tmp_path / "config" / "settings.json"
    config.parent.mkdir()
    config.write_text(
        json.dumps(
            {
                "paths": {"input_dir": "data/input"},
                "files": {"supported_extensions": [".csv"]},
                "connectors": options,
            }
        ),
        encoding="utf-8",
    )
    return config


def test_write_sqlite_creates_table(tmp_path: Path) -> None:
    destination = tmp_path / "output.db"
    write_sqlite(pd.DataFrame({"id": [1], "name": ["Ada"]}), destination, "customers")

    with sqlite3.connect(destination) as connection:
        rows = connection.execute("SELECT id, name FROM customers").fetchall()
    assert rows == [(1, "Ada")]


def test_write_sqlite_rejects_unsafe_table_name(tmp_path: Path) -> None:
    with pytest.raises(DeliveryError, match="table"):
        write_sqlite(
            pd.DataFrame({"id": [1]}),
            tmp_path / "output.db",
            "customers; DROP TABLE users",
        )


def test_post_json_posts_records(monkeypatch, tmp_path: Path) -> None:
    settings = load_settings(
        write_settings(tmp_path, allowed_hosts=["api.example.com"])
    )
    captured: dict[str, object] = {}

    class Response:
        status = 201

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    def fake_urlopen(request: object, timeout: float) -> Response:
        captured["request"] = request
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("datake.delivery.urlopen", fake_urlopen)

    status = post_json(
        pd.DataFrame({"id": [1]}),
        "https://api.example.com/products",
        settings,
    )

    request = captured["request"]
    assert status == 201
    assert captured["timeout"] == 15
    assert request.data == b'[{"id":1}]'
