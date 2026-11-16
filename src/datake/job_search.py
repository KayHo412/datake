"""Local job-listing normalization, deduplication, and application tracking."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class JobListing:
    """A normalized job listing suitable for manual review."""

    title: str
    company: str
    location: str
    url: str
    remote: str
    salary: str
    posted_at: str
    status: str = "new"
    notes: str = ""

    @property
    def listing_id(self) -> str:
        identity = "|".join(
            value.strip().lower()
            for value in (self.title, self.company, self.location, self.url)
        )
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


class JobSearchStore:
    """SQLite-backed store for listings and manually maintained applications."""

    def __init__(self, database: Path) -> None:
        self.database = database
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(database) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS job_listings (
                    listing_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    company TEXT NOT NULL,
                    location TEXT NOT NULL,
                    url TEXT NOT NULL,
                    remote TEXT NOT NULL,
                    salary TEXT NOT NULL,
                    posted_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def import_listings(self, listings: list[JobListing]) -> int:
        """Insert new listings and update duplicate metadata without duplication."""
        inserted = 0
        with sqlite3.connect(self.database) as connection:
            for listing in listings:
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO job_listings
                        (listing_id, title, company, location, url, remote, salary,
                         posted_at, status, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        listing.listing_id,
                        listing.title,
                        listing.company,
                        listing.location,
                        listing.url,
                        listing.remote,
                        listing.salary,
                        listing.posted_at,
                        listing.status,
                        listing.notes,
                    ),
                )
                inserted += cursor.rowcount
        return inserted

    def list_listings(self, *, status: str | None = None) -> list[dict[str, Any]]:
        query = """
            SELECT listing_id, title, company, location, url, remote, salary,
                   posted_at, status, notes
            FROM job_listings
        """
        parameters: tuple[str, ...] = ()
        if status:
            query += " WHERE status = ?"
            parameters = (status,)
        query += " ORDER BY posted_at DESC, company, title"
        with sqlite3.connect(self.database) as connection:
            rows = connection.execute(query, parameters).fetchall()
        names = (
            "listing_id",
            "title",
            "company",
            "location",
            "url",
            "remote",
            "salary",
            "posted_at",
            "status",
            "notes",
        )
        return [dict(zip(names, row, strict=True)) for row in rows]

    def update_listing(
        self,
        listing_id: str,
        *,
        status: str | None = None,
        notes: str | None = None,
    ) -> None:
        updates: list[str] = []
        values: list[str] = []
        if status is not None:
            if status not in {"new", "reviewed", "applied", "interview", "rejected"}:
                raise ValueError(f"Unsupported application status: {status}")
            updates.append("status = ?")
            values.append(status)
        if notes is not None:
            updates.append("notes = ?")
            values.append(notes)
        if not updates:
            raise ValueError("Provide status or notes to update")
        values.append(listing_id)
        with sqlite3.connect(self.database) as connection:
            cursor = connection.execute(
                f"UPDATE job_listings SET {', '.join(updates)} WHERE listing_id = ?",
                values,
            )
        if cursor.rowcount == 0:
            raise ValueError(f"Unknown listing: {listing_id}")

    def export_excel(self, output: Path) -> Path:
        """Export listings and a status summary as separate Excel sheets."""
        listings = self.list_listings()
        frame = pd.DataFrame(listings)
        summary = (
            frame.groupby("status", as_index=False)
            .size()
            .rename(columns={"size": "count"})
            if not frame.empty
            else pd.DataFrame(columns=["status", "count"])
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            frame.to_excel(writer, sheet_name="Job matches", index=False)
            summary.to_excel(writer, sheet_name="Summary", index=False)
        return output


def read_job_feed(path: Path) -> list[JobListing]:
    """Read an approved local CSV, JSON array, or JSON-lines feed."""
    if path.suffix.lower() == ".csv":
        frame = pd.read_csv(path)
    elif path.suffix.lower() == ".jsonl":
        frame = pd.read_json(path, lines=True)
    elif path.suffix.lower() == ".json":
        frame = pd.read_json(path)
    else:
        raise ValueError("Job feed must be .csv, .json, or .jsonl")
    frame = frame.fillna("")
    aliases = {
        "job_title": "title",
        "employer": "company",
        "city": "location",
        "link": "url",
        "is_remote": "remote",
        "compensation": "salary",
        "date_posted": "posted_at",
    }
    frame = frame.rename(columns=aliases)
    required = {"title", "company", "url"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Job feed is missing columns: {', '.join(sorted(missing))}")
    return [
        JobListing(
            title=str(row.get("title", "")),
            company=str(row.get("company", "")),
            location=str(row.get("location", "")),
            url=str(row.get("url", "")),
            remote=str(row.get("remote", "")),
            salary=str(row.get("salary", "")),
            posted_at=str(row.get("posted_at", "")),
        )
        for _, row in frame.iterrows()
    ]
