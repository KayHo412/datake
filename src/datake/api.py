"""Minimal HTTP API for uploading and processing tabular files."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from datake.automation import write_report
from datake.config import Settings, load_settings
from datake.history import ProcessingHistory
from datake.job_search import JobSearchStore, read_job_feed
from datake.processor import ProcessResult, process_file

MAX_UPLOAD_BYTES = 50 * 1024 * 1024


@dataclass
class ApiJob:
    """In-memory record for one API processing job."""

    job_id: str
    file_id: str
    filename: str
    status: str
    result: ProcessResult | None = None
    report_path: Path | None = None
    output_path: Path | None = None
    error: str | None = None


class ApiStore:
    """Persist API file and job metadata in the application history database."""

    def __init__(self, settings: Settings) -> None:
        self.path = settings.history_db
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS api_files (
                    file_id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    path TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS api_jobs (
                    job_id TEXT PRIMARY KEY,
                    file_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    status TEXT NOT NULL,
                    rows_in INTEGER,
                    rows_out INTEGER,
                    rejected_rows INTEGER,
                    report_path TEXT,
                    output_path TEXT,
                    error TEXT
                );
                """
            )

    def save_file(self, file_id: str, filename: str, path: Path) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "INSERT INTO api_files (file_id, filename, path) VALUES (?, ?, ?)",
                (file_id, filename, str(path)),
            )

    def files(self) -> dict[str, Path]:
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute("SELECT file_id, path FROM api_files").fetchall()
        return {row[0]: Path(row[1]) for row in rows}

    def save_job(self, job: ApiJob) -> None:
        clean = job.result.clean_result if job.result else None
        output = job.output_path or (job.result.output_path if job.result else None)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO api_jobs
                    (job_id, file_id, filename, status, rows_in, rows_out,
                     rejected_rows, report_path, output_path, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.job_id,
                    job.file_id,
                    job.filename,
                    job.status,
                    clean.rows_in if clean else None,
                    clean.rows_out if clean else None,
                    len(clean.rejected_dataframe) if clean else None,
                    str(job.report_path) if job.report_path else None,
                    str(output) if output else None,
                    job.error,
                ),
            )

    def load_job(self, job_id: str) -> ApiJob | None:
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                """
                SELECT job_id, file_id, filename, status, rows_in, rows_out,
                       rejected_rows, report_path, output_path, error
                FROM api_jobs WHERE job_id = ?
                """,
                (job_id,),
            ).fetchone()
        if row is None:
            return None
        return ApiJob(
            job_id=row[0],
            file_id=row[1],
            filename=row[2],
            status=row[3],
            report_path=Path(row[7]) if row[7] else None,
            output_path=Path(row[8]) if row[8] else None,
            error=row[9],
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the Datake API application."""
    runtime = settings or load_settings()
    store = ApiStore(runtime)
    upload_dir = runtime.project_root / "data" / "api_uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    files = store.files()
    jobs: dict[str, ApiJob] = {}
    lock = Lock()

    app = FastAPI(title="Datake API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def require_api_key(request: Request) -> None:
        expected = os.getenv("DATAKE_API_KEY")
        if expected and request.headers.get("x-api-key") != expected:
            raise HTTPException(status_code=401, detail="Invalid or missing API key")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": "0.1.0"}

    @app.get("/dashboard")
    def dashboard(request: Request) -> dict[str, object]:
        """Return aggregate processing and privacy metadata for a dashboard."""
        require_api_key(request)
        summary = ProcessingHistory(runtime).summary(limit=20)
        reports: list[dict[str, object]] = []
        for run in summary.recent_runs:
            if not run.report_path or not run.report_path.is_file():
                continue
            payload = json.loads(run.report_path.read_text(encoding="utf-8"))
            reports.append(
                {
                    "source_path": payload.get("source_path"),
                    "status": payload.get("status"),
                    "rows_in": payload.get("rows_in"),
                    "rows_out": payload.get("rows_out"),
                    "rejected_rows": payload.get("rejected_rows"),
                    "sensitive_columns": payload.get("sensitive_columns", {}),
                    "created_at": payload.get("created_at"),
                }
            )
        return {
            "total_runs": summary.total,
            "successful_runs": summary.successful,
            "failed_runs": summary.failed,
            "recent_runs": reports,
        }

    @app.get("/jobs/listings")
    def list_job_listings(
        request: Request,
        status: str | None = None,
    ) -> dict[str, object]:
        require_api_key(request)
        store = JobSearchStore(runtime.history_db)
        return {"listings": store.list_listings(status=status)}

    @app.post("/jobs/listings/import", status_code=201)
    async def import_job_listings(
        request: Request,
        file: UploadFile = File(...),
    ) -> dict[str, object]:
        require_api_key(request)
        filename = Path(file.filename or "").name
        suffix = Path(filename).suffix.lower()
        if suffix not in {".csv", ".json", ".jsonl"}:
            raise HTTPException(
                status_code=415,
                detail="Job feed must be .csv, .json, or .jsonl",
            )
        content = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="File is too large")
        feed_path = (
            runtime.project_root
            / "data"
            / "api_uploads"
            / f"jobs_{uuid.uuid4().hex}{suffix}"
        )
        feed_path.parent.mkdir(parents=True, exist_ok=True)
        feed_path.write_bytes(content)
        try:
            store = JobSearchStore(runtime.history_db)
            inserted = store.import_listings(read_job_feed(feed_path))
            return {"imported": inserted, "filename": filename}
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            feed_path.unlink(missing_ok=True)

    @app.patch("/jobs/listings/{listing_id}")
    async def update_job_listing(
        listing_id: str,
        request: Request,
    ) -> dict[str, object]:
        require_api_key(request)
        try:
            payload = await request.json()
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="JSON object required")
        status_value = payload.get("status")
        notes = payload.get("notes")
        if status_value is not None and not isinstance(status_value, str):
            raise HTTPException(status_code=400, detail="Status must be a string")
        if notes is not None and not isinstance(notes, str):
            raise HTTPException(status_code=400, detail="Notes must be a string")
        try:
            JobSearchStore(runtime.history_db).update_listing(
                listing_id,
                status=status_value,
                notes=notes,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        listings = JobSearchStore(runtime.history_db).list_listings()
        listing = next(
            (item for item in listings if item["listing_id"] == listing_id),
            None,
        )
        if listing is None:
            raise HTTPException(status_code=404, detail="Listing not found")
        return listing

    @app.post("/jobs/listings/export")
    def export_job_listings(request: Request) -> FileResponse:
        require_api_key(request)
        output = runtime.project_root / "data" / "reports" / "job_checklist.xlsx"
        JobSearchStore(runtime.history_db).export_excel(output)
        return FileResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename="job_checklist.xlsx",
        )

    @app.post("/files", status_code=201)
    async def upload_file(
        request: Request,
        file: UploadFile = File(...),
    ) -> dict[str, object]:
        require_api_key(request)
        filename = Path(file.filename or "").name
        suffix = Path(filename).suffix.lower()
        if not filename or suffix not in runtime.supported_extensions:
            supported = ", ".join(runtime.supported_extensions)
            raise HTTPException(
                status_code=415,
                detail=f"Unsupported file type. Supported: {supported}",
            )

        content = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="File is too large")

        file_id = uuid.uuid4().hex
        stored_path = upload_dir / f"{file_id}{suffix}"
        stored_path.write_bytes(content)
        with lock:
            files[file_id] = stored_path
        store.save_file(file_id, filename, stored_path)
        return {
            "file_id": file_id,
            "filename": filename,
            "size_bytes": len(content),
            "status": "uploaded",
        }

    @app.post("/webhooks/{source}", status_code=202)
    async def receive_webhook(source: str, request: Request) -> dict[str, object]:
        """Store an approved JSON webhook payload for normal file processing."""
        require_api_key(request)
        safe_source = "".join(
            character
            for character in source
            if character.isalnum() or character in "-_"
        )
        if not safe_source:
            raise HTTPException(status_code=400, detail="Invalid webhook source")
        content_type = request.headers.get("content-type", "").split(";", 1)[0]
        if content_type != "application/json":
            raise HTTPException(status_code=415, detail="Webhook must send JSON")
        content = await request.body()
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Payload is too large")
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc
        if not isinstance(payload, (list, dict)):
            raise HTTPException(status_code=400, detail="JSON object or array required")
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
        path = runtime.input_dir / f"webhook_{safe_source}_{timestamp}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return {"status": "accepted", "path": str(path)}

    @app.post("/files/{file_id}/process", status_code=202)
    def process_uploaded_file(
        file_id: str,
        request: Request,
        background_tasks: BackgroundTasks,
    ) -> dict[str, object]:
        require_api_key(request)
        source = files.get(file_id)
        if source is None:
            raise HTTPException(status_code=404, detail="File not found")

        job_id = uuid.uuid4().hex
        job = ApiJob(
            job_id=job_id,
            file_id=file_id,
            filename=source.name,
            status="queued",
        )
        with lock:
            jobs[job_id] = job
        store.save_job(job)
        background_tasks.add_task(process_api_job, job_id, source)
        return _job_payload(job)

    @app.get("/jobs/{job_id}")
    def get_job(job_id: str, request: Request) -> dict[str, object]:
        require_api_key(request)
        job = jobs.get(job_id) or store.load_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return _job_payload(job)

    @app.get("/jobs/{job_id}/report")
    def get_job_report(job_id: str, request: Request) -> dict[str, object]:
        require_api_key(request)
        job = jobs.get(job_id) or store.load_job(job_id)
        if job is None or job.report_path is None:
            raise HTTPException(status_code=404, detail="Report not found")
        return json.loads(job.report_path.read_text(encoding="utf-8"))

    @app.get("/files/{file_id}/download")
    def download_file(file_id: str, request: Request) -> FileResponse:
        require_api_key(request)
        source = files.get(file_id)
        if source is None:
            raise HTTPException(status_code=404, detail="File not found")
        job = next((item for item in jobs.values() if item.file_id == file_id), None)
        if job is None:
            raise HTTPException(status_code=404, detail="Processed file not found")
        output_path = job.output_path or (
            job.result.output_path if job.result else None
        )
        if (
            job.status != "completed"
            or output_path is None
            or not output_path.is_file()
        ):
            raise HTTPException(status_code=404, detail="Processed file not found")
        return FileResponse(
            output_path,
            media_type=_media_type(output_path),
            filename=output_path.name,
        )

    def process_api_job(job_id: str, source: Path) -> None:
        job = jobs[job_id]
        job.status = "running"
        store.save_job(job)
        try:
            result = process_file(source, runtime, write_output=True)
            job.result = result
            job.output_path = result.output_path
            job.status = "completed" if result.succeeded else "failed"
            job.error = result.error
            if result.succeeded:
                job.report_path = write_report(
                    result,
                    runtime,
                    hashlib.sha256(source.read_bytes()).hexdigest(),
                )
            ProcessingHistory(runtime).record(
                source,
                hashlib.sha256(source.read_bytes()).hexdigest(),
                result.status,
                report_path=job.report_path,
                error=result.error,
            )
        except (OSError, ValueError, RuntimeError) as exc:
            job.status = "failed"
            job.error = str(exc)
        store.save_job(job)

    return app


def _job_payload(job: ApiJob) -> dict[str, object]:
    result = job.result
    clean_result = result.clean_result if result else None
    return {
        "job_id": job.job_id,
        "file_id": job.file_id,
        "filename": job.filename,
        "status": job.status,
        "rows_in": clean_result.rows_in if clean_result else None,
        "rows_out": clean_result.rows_out if clean_result else None,
        "rejected_rows": (
            len(clean_result.rejected_dataframe) if clean_result else None
        ),
        "report_available": job.report_path is not None,
        "error": job.error,
    }


def _media_type(path: Path) -> str:
    return {
        ".csv": "text/csv",
        ".json": "application/json",
        ".jsonl": "application/x-ndjson",
        ".parquet": "application/vnd.apache.parquet",
    }.get(path.suffix.lower(), "application/octet-stream")


app = create_app()

frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
