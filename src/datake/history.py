"""Persistent processing history used for idempotent automation."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from datake.config import Settings


def file_hash(path: Path) -> str:
    """Return a stable SHA-256 digest for a file."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ProcessingHistory:
    """Small SQLite store recording the latest outcome for each file hash."""

    def __init__(self, settings: Settings) -> None:
        self.path = settings.history_db
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS processing_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_path TEXT NOT NULL,
                    file_hash TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    report_path TEXT,
                    error TEXT
                )
                """
            )

    def has_success(self, digest: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM processing_runs "
                "WHERE file_hash = ? AND status = 'success' LIMIT 1",
                (digest,),
            ).fetchone()
        return row is not None

    def record(
        self,
        source_path: Path,
        digest: str,
        status: str,
        *,
        report_path: Path | None = None,
        error: str | None = None,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO processing_runs
                    (source_path, file_hash, status, started_at, completed_at,
                     report_path, error)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(file_hash) DO UPDATE SET
                    source_path = excluded.source_path,
                    status = excluded.status,
                    completed_at = excluded.completed_at,
                    report_path = excluded.report_path,
                    error = excluded.error
                """,
                (
                    str(source_path),
                    digest,
                    status,
                    now,
                    now,
                    str(report_path) if report_path else None,
                    error,
                ),
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)
