from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from datake.job_search import JobSearchStore, read_job_feed


def test_import_deduplicates_and_tracks_status(tmp_path: Path) -> None:
    feed = tmp_path / "jobs.json"
    feed.write_text(
        json.dumps(
            [
                {
                    "title": "Data Analyst",
                    "company": "Example",
                    "location": "Remote",
                    "url": "https://example.test/jobs/1",
                },
                {
                    "title": "Data Analyst",
                    "company": "Example",
                    "location": "Remote",
                    "url": "https://example.test/jobs/1",
                },
            ]
        ),
        encoding="utf-8",
    )
    store = JobSearchStore(tmp_path / "jobs.db")

    assert store.import_listings(read_job_feed(feed)) == 1
    listing = store.list_listings()[0]
    store.update_listing(listing["listing_id"], status="applied", notes="Sent CV")

    updated = store.list_listings(status="applied")
    assert updated[0]["notes"] == "Sent CV"


def test_export_excel_contains_matches_and_summary(tmp_path: Path) -> None:
    feed = tmp_path / "jobs.csv"
    pd.DataFrame(
        [
            {
                "title": "Engineer",
                "company": "Example",
                "url": "https://example.test/1",
            }
        ]
    ).to_csv(feed, index=False)
    store = JobSearchStore(tmp_path / "jobs.db")
    store.import_listings(read_job_feed(feed))

    output = store.export_excel(tmp_path / "checklist.xlsx")

    assert output.is_file()
    assert set(pd.ExcelFile(output).sheet_names) == {"Job matches", "Summary"}
