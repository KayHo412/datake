# Datake

Automated data processing tool for CSV and Excel files.

This project is being built in phases. **Phases 1–17 are implemented**: read,
validate, profile, compare, clean, merge, monitor, inspect processing history,
collect from approved sources, deliver cleaned data, run repeatable jobs, expose
a protected API, and maintain a review-first job checklist across CSV, Excel
(`.xlsx`), JSON, JSON Lines, and Parquet files.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Usage

```bash
datake read data/input/sample_customers.csv
datake read data/input/sample_customers.xlsx
datake validate data/input/sample_customers_dirty.csv
datake validate data/input/sample_customers_dirty.csv --profile lenient_customer_import
datake profile data/input/sample_customers_dirty.csv
datake profile data/input/sample_customers_dirty.csv --json
datake compare data/input/old.csv data/input/new.csv --key customer_id
datake compare data/input/old.csv data/input/new.csv --key customer_id --json
datake clean data/input/sample_customers_dirty.csv
datake clean data/input/sample_customers_dirty.csv --profile lenient_customer_import
datake profiles
datake fetch https://api.example.com/products --output data/input/products.json
datake fetch-csv https://docs.google.com/spreadsheets/d/ID/export?format=csv \
  --output data/input/products.csv
datake fetch-sqlite data/source.db "SELECT * FROM products" \
  --output data/input/products.csv
datake export data/input/products.csv \
  --sqlite data/destinations/catalog.db --table products --if-exists replace
datake merge
datake watch --once
datake watch
datake status
datake status --json
datake report --status failed
datake report --json
datake watch --once --dry-run
datake job run input_cleanup
datake job run input_cleanup --dry-run
datake job watch input_cleanup
datake job cancel input_cleanup
datake job status
```

- `read` — load a CSV or `.xlsx` file and show rows (does not change it)
- `validate` — list quality problems (does not change it)
- `validate --profile NAME` — apply a named validation and cleaning rule profile
- `profile` — summarize columns, missing values, duplicates, and common values
  without changing the file; numeric IQR outliers and singleton values are
  reported as unusual values
- `compare` — report rows added, removed, and changed between two datasets;
  use repeated `--key` options to match records by one or more columns
- `clean` — write a cleaned copy to `data/processed/` (original stays in `data/input/`)
- `clean --profile NAME` — clean using a named rule profile
- `profiles` — list named profiles configured in `settings.json`
- `fetch` — fetch an approved JSON API response into a `.json` input file
- `fetch-csv` — fetch an approved CSV URL, including a published Google Sheet
- `fetch-sqlite` — run a read-only SQLite query into a Datake input file
- `fetch-postgres` — run a read-only PostgreSQL query (connector extra required)
- `fetch-sftp` — fetch an SFTP file (connector extra required)
- `fetch-s3` — fetch an S3 object (connector extra required)
- `export` — clean and deliver a dataset to SQLite, an approved HTTP API, or S3
- `merge` — clean files in `data/input/` and combine those with the same columns
- `watch --once` — process the current input batch and exit
- `watch` — poll `data/input/` continuously for new files
- `status` — show run totals and recent automated processing outcomes
- `status --json` — emit status data for scripts and monitoring tools
- `report` — list recorded processing runs, optionally filtered by status
- `report --json` — emit report history for scripts and monitoring tools
- `watch --dry-run` — preview files without writing output, moving files, or
  recording history
- `job run NAME` — run a configured repeatable job once
- `job watch NAME` — run a configured job on its interval
- `job cancel NAME` — request cancellation of a running job
- `job status` — show persistent job runs and outcomes

## Automated processing

`watch` makes file processing idempotent and auditable:

- Successfully processed inputs move to `data/archive/`.
- Files that cannot be read or processed move to `data/quarantine/`.
- Rejected rows are preserved in `data/quarantine/*_rejected.csv` with a
  `rejection_reason` column.
- Each run creates a JSON report in `data/reports/`.
- `data/datake.db` stores SHA-256 file hashes and run outcomes, so the same
  file content is not processed twice.

The default polling interval is five seconds and can be changed in
`config/settings.json`:

```json
{
  "automation": {
    "watch_interval": 5,
    "file_stability_seconds": 2
  }
}
```

For a one-off batch, use `datake watch --once`. For a long-running worker,
use `datake watch` and stop it with `Ctrl-C`. The optional `--interval` flag
overrides the configured interval for that run.

Cleaning rules live in `config/settings.json` under `"cleaning"`.

Use `datake status --limit 20` to inspect more recent runs. The command reports
successful and failed runs from the SQLite history without modifying data.

The default supported input extensions are `.csv`, `.xlsx`, `.json`, `.jsonl`,
and `.parquet`. Excel files are read from their first worksheet. JSON files use
an array of objects, JSON Lines uses one object per line, and Parquet files use
their first table. Cleaned outputs use the `files.output_format` setting and
default to CSV:

```json
{
  "files": {
    "supported_extensions": [".csv", ".xlsx", ".json", ".jsonl", ".parquet"],
    "output_format": "parquet"
  }
}
```

Parquet support uses the `pyarrow` dependency installed by the project.
For large files copied into `data/input`, set `file_stability_seconds` so the
watcher waits until size and modification time stop changing before reading.

## REST connector

Phase 12 begins with a deliberately narrow REST connector. It performs a
read-only HTTP GET for an approved JSON endpoint and saves an array of records
as a normal `.json` input file:

```bash
datake fetch https://api.example.com/products \
  --output data/input/products.json
datake validate data/input/products.json
datake clean data/input/products.json
```

Configure connector safety limits in `settings.json`:

```json
{
  "connectors": {
    "timeout_seconds": 15,
    "max_response_bytes": 10485760,
    "allowed_hosts": ["api.example.com"],
    "user_agent": "Datake/0.1"
  }
}
```

The connector accepts a top-level array or an array under `data`, `results`, or
`items`. It does not log in, bypass authentication, solve CAPTCHAs, scrape
paywalled content, or bypass robots rules. Use it only with sources that
explicitly permit automated access and configure `allowed_hosts` in production.

## Tests

```bash
pytest
```

## Try the backend MVP

Install the API dependencies:

```bash
pip install -e ".[dev]"
```

Start the local server from the project directory:

```bash
uvicorn datake.api:app --reload
```

Open the integrated web interface at
[`http://127.0.0.1:8000`](http://127.0.0.1:8000), or the interactive API page at
[`http://127.0.0.1:8000/docs`](http://127.0.0.1:8000/docs). The MVP supports:

- `GET /health` — check that the server is running.
- `POST /files` — upload a CSV or `.xlsx` file.
- `POST /files/{file_id}/process` — clean the uploaded file.
- `GET /jobs/{job_id}` — see processing results.
- `GET /jobs/{job_id}/report` — read the JSON report.
- `GET /files/{file_id}/download` — download the cleaned CSV.

API files and job metadata are persisted in the configured SQLite history
database, while processing runs in a FastAPI background task. Clients should
poll `GET /jobs/{job_id}` until the status is `completed` or `failed`.
Set `DATAKE_API_KEY` to require an `X-API-Key` header on all file, webhook, job,
and download endpoints; `/health` remains public.

For frontend development, run Vite separately:

```bash
cd frontend
npm install
npm run dev
```

Open [`http://127.0.0.1:5173`](http://127.0.0.1:5173). Vite proxies `/api`
requests to the FastAPI server on port `8000`. Run `npm run build` to rebuild
the integrated UI served by FastAPI at `/`.

## Backend MVP

Datake now includes a small FastAPI backend for trying the processing workflow
from another application:

```bash
uvicorn datake.api:app --reload
```

Open [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) to use the
interactive API page. The available endpoints are:

- `GET /health`
- `POST /files`
- `POST /files/{file_id}/process`
- `GET /jobs/{job_id}`
- `GET /jobs/{job_id}/report`
- `GET /files/{file_id}/download`

The backend accepts all configured tabular uploads, queues processing in the
background, stores files and job metadata locally, and returns a cleaned file
and JSON report. API job metadata survives server restarts.

## Future roadmap

Datake currently has a command-line tool and a small backend MVP that read,
check, profile, compare, clean, report, collect, deliver, and automate data.
The completed phases below describe the current implementation; future work is
called out explicitly within each phase.

### Phase 9 — Understand data before changing it (complete)

- The `profile` command now summarizes columns, missing values, duplicates,
  common values, numeric ranges, and a simple data-quality score.
- `profile` reports numeric IQR outliers and singleton categorical values as
  unusual values.
- `compare` reports added, removed, and changed rows. With `--key`, rows are
  matched by stable identifiers; without it, complete row values are compared.

The intended workflow is:

```text
profile -> validate -> dry-run -> clean -> compare -> publish
```

### Phase 10 — Support more formats (complete)

- JSON, JSON Lines, and Parquet are supported as inputs and outputs.
- CSV remains the default output format for compatibility.
- `files.output_format` selects `csv`, `json`, `jsonl`, or `parquet`.

Named validation and cleaning profiles are now supported. A profile can
override required columns, uniqueness, email and numeric rules, aliases, fills,
date handling, and row-removal behavior without duplicating the base settings.
Select one with `--profile NAME`; `datake profiles` lists available profiles.

For example:

```json
{
  "profiles": {
    "lenient_customer_import": {
      "validation": {
        "required_columns": ["customer_id"],
        "email_columns": []
      },
      "cleaning": {
        "drop_if_missing": ["customer_id"]
      }
    }
  }
}
```

The same profile selection is available to `watch --profile NAME`, so files
from an automated source use the same explicit rules as manual processing.

### Phase 11 — Reusable data rules (complete)

- Named rule profiles are loaded from `settings.json`.
- Validation and cleaning commands can select a profile.
- Automated watching can select a profile.
- Existing top-level `validation` and `cleaning` settings remain the default.

Add reusable transformations such as:

- Renaming and standardizing fields.
- Converting dates and numbers.
- Mapping categories.
- Filtering and deduplicating records.
- Joining or summarizing datasets.

### Phase 12 — Collect data from other places (complete)

- REST/JSON and CSV URL connectors are implemented with host allowlisting,
  timeouts, response-size limits, and the existing validation/cleaning flow.
- Published Google Sheets can be collected through their CSV export URL.
- Read-only SQLite and PostgreSQL query connectors are available.
- SFTP and S3 object connectors use optional dependencies and environment-based
  credentials.
- `POST /webhooks/{source}` accepts JSON payloads and writes them into the
  normal input directory for validation and cleaning.
- All connectors produce normal Datake input files, so they share the same
  validation, cleaning, reporting, and history pipeline.

Collection from websites is limited to explicitly approved structured JSON or
CSV endpoints. Datake does not scrape arbitrary pages.

Website collection should create a table internally and send it through the
same validation, cleaning, reporting, and history system. A user would not
need to upload a CSV for this workflow.

The future website workflow is:

```text
approved website -> collect information -> validate -> clean -> report
```

Datake must respect website terms, robots rules, request limits, and privacy.
It must not bypass passwords, CAPTCHA systems, paywalls, or other security
controls.

### Phase 13 — Deliver data to useful destinations (complete)

- `export` delivers cleaned datasets to SQLite tables, approved HTTP JSON APIs,
  and S3 objects.
- Existing local outputs remain available in CSV, Excel, JSON, or Parquet.

Database tables, cloud storage, and another approved API are now supported.
Destinations use explicit allowlisting and size limits where applicable.

This will allow workflows such as:

```text
online shop -> Datake -> clean data -> company database
```

### Phase 14 — Run repeatable jobs automatically (complete)

Saved jobs can run on an interval or once on demand. Jobs process the normal
input directory and use the same cleaning, reporting, archive, quarantine, and
history behavior as `watch`.

- Job definitions are stored in `settings.json` under `"jobs"`.
- Jobs support retry counts, dry runs, cancellation, and persistent SQLite
  run history.
- Use `job status` to inspect attempts, processed-file counts, and outcomes.
- Jobs can optionally POST success, failure, and cancellation events to an
  approved webhook. Notification delivery failures are logged without changing
  the processing result.

Configure a webhook per job:

```json
{
  "name": "input_cleanup",
  "webhook_url": "https://hooks.example.test/datake",
  "notification_events": ["success", "failure"],
  "notification_retries": 2
}
```

Webhook hosts must be included in `connectors.allowed_hosts` when host
allowlisting is enabled. Email, Slack, and Teams adapters remain future work.

### Phase 15 — Backend API hardening (complete)

Expose Datake through a web backend so a website or another application can
use it. The current API supports file uploads, queued processing, persistent
metadata, and optional API-key protection:

```text
POST /files
POST /files/{file_id}/process
GET  /files/{file_id}
GET  /files/{file_id}/download
GET  /dashboard
```

Processing runs in the background so a web request does not need to wait for
completion. API metadata is persisted in SQLite, and optional `DATAKE_API_KEY`
protection is available for non-health endpoints. Collection connectors and
repeatable jobs remain available through their dedicated CLI workflows.

### Phase 16 — Reports, dashboards, and privacy (complete)

Reports now include conservative, name-based privacy metadata without copying
cell values. The API also exposes `GET /dashboard`, which returns aggregate
processing totals, recent quality metrics, rejected-row counts, and detected
sensitive column names for a dashboard client.

```text
GET /dashboard
```

Likely personal-data columns are classified as email, phone, name, or address.
This detection is intentionally metadata-only and should be reviewed before
making privacy decisions.

Reports and dashboards can show:

- Sales or other business summaries.
- Processing history.
- Quality scores over time.
- Rejected-row trends.
- Changes between runs.
- Failed jobs and warnings.

Future privacy features could include:

- Detecting personal information.
- Hiding or hashing names, emails, phone numbers, and addresses.
- Creating safe test data.
- Access control and audit history.

AI-assisted explanations may eventually summarize unusual patterns or suggest
rules, but production cleaning decisions should remain controlled by explicit,
repeatable rules.

### Phase 17 — Job search and application checklist (complete)

Datake now supports a local, review-first job-search workflow using approved
CSV, JSON, or JSON Lines feeds. It does not bypass
logins, CAPTCHA systems, paywalls, or other security controls.

The implemented workflow is:

```text
approved job sources -> find matching jobs -> remove duplicates
-> track applications -> export an Excel checklist
```

Supported features include:

- Search by job title, location, remote status, salary, skills, and posting date.
- Remove duplicate job listings and remember jobs already reviewed.
- Score or group jobs against user preferences.
- Track application status, deadlines, follow-ups, interviews, and notes.
- Export sheets for job matches, application tasks, applications, and a summary.
- Add reminders without automatically submitting applications.

Import a feed and deduplicate listings:

```bash
datake jobs import data/jobs.json
datake jobs list
```

Track a listing manually:

```bash
datake jobs update LISTING_ID --status applied --notes "Sent CV"
datake jobs list --status applied
```

Export the current checklist:

```bash
datake jobs export --output data/job-checklist.xlsx
```

The checklist is stored in the configured SQLite history database and contains
job matches plus a status summary. Supported statuses are `new`, `reviewed`,
`applied`, `interview`, and `rejected`. The user should review and submit
applications themselves; Datake does not automatically apply.
