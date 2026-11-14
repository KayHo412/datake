"""Persistent control and execution for repeatable Datake jobs."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from datake.automation import process_new_files
from datake.config import JobSettings, Settings, load_settings


@dataclass(frozen=True)
class JobRun:
    job_name: str
    status: str
    attempts: int
    processed_count: int
    started_at: str
    completed_at: str
    error: str | None


class JobStore:
    """SQLite-backed job run and cancellation state."""

    def __init__(self, settings: Settings) -> None:
        self.path = settings.history_db
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS job_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL,
                    processed_count INTEGER NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT NOT NULL,
                    error TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS job_controls (
                    job_name TEXT PRIMARY KEY,
                    cancelled INTEGER NOT NULL DEFAULT 0
                )
                """
            )

    def cancel(self, name: str) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                INSERT INTO job_controls(job_name, cancelled) VALUES (?, 1)
                ON CONFLICT(job_name) DO UPDATE SET cancelled = 1
                """,
                (name,),
            )

    def reset_cancelled(self, name: str) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                INSERT INTO job_controls(job_name, cancelled) VALUES (?, 0)
                ON CONFLICT(job_name) DO UPDATE SET cancelled = 0
                """,
                (name,),
            )

    def is_cancelled(self, name: str) -> bool:
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                "SELECT cancelled FROM job_controls WHERE job_name = ?", (name,)
            ).fetchone()
        return bool(row and row[0])

    def record(self, run: JobRun) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                INSERT INTO job_runs
                (job_name, status, attempts, processed_count, started_at,
                 completed_at, error)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.job_name,
                    run.status,
                    run.attempts,
                    run.processed_count,
                    run.started_at,
                    run.completed_at,
                    run.error,
                ),
            )

    def runs(self, name: str | None = None, limit: int = 20) -> tuple[JobRun, ...]:
        query = """
            SELECT job_name, status, attempts, processed_count, started_at,
                   completed_at, error
            FROM job_runs
        """
        parameters: tuple[object, ...] = ()
        if name:
            query += " WHERE job_name = ?"
            parameters = (name,)
        query += " ORDER BY id DESC LIMIT ?"
        parameters += (limit,)
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(query, parameters).fetchall()
        return tuple(JobRun(*row) for row in rows)


def find_job(settings: Settings, name: str) -> JobSettings:
    for job in settings.jobs:
        if job.name == name:
            if not job.enabled:
                raise ValueError(f"Job {name!r} is disabled")
            return job
    available = ", ".join(job.name for job in settings.jobs) or "none"
    raise ValueError(f"Unknown job {name!r}. Available jobs: {available}")


def run_job(settings: Settings, name: str, *, dry_run: bool = False) -> JobRun:
    """Run one configured job, retrying failed attempts as configured."""
    job = find_job(settings, name)
    runtime = (
        load_settings(settings.config_path, profile=job.profile)
        if job.profile
        else settings
    )
    store = JobStore(settings)
    started = datetime.now(UTC).isoformat()
    last_error: str | None = None
    processed_count = 0
    attempts = 0
    for attempts in range(1, job.retries + 2):
        if store.is_cancelled(name):
            break
        try:
            results = process_new_files(runtime, dry_run=dry_run)
            processed_count = len(results)
            last_error = None
            break
        except (OSError, ValueError, RuntimeError) as exc:
            last_error = str(exc)
            if attempts <= job.retries:
                time.sleep(min(2**attempts, 30))
    cancelled = store.is_cancelled(name)
    status = "cancelled" if cancelled else ("failed" if last_error else "success")
    completed = datetime.now(UTC).isoformat()
    run = JobRun(
        name,
        status,
        attempts,
        processed_count,
        started,
        completed,
        last_error,
    )
    store.record(run)
    return run


def watch_job(
    settings: Settings,
    name: str,
    *,
    dry_run: bool = False,
) -> None:
    """Run a job repeatedly until it is cancelled or interrupted."""
    job = find_job(settings, name)
    JobStore(settings).reset_cancelled(name)
    while not JobStore(settings).is_cancelled(name):
        run_job(settings, name, dry_run=dry_run)
        time.sleep(job.interval)
