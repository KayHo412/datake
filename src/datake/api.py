"""Minimal HTTP API for uploading and processing tabular files."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from datake.automation import write_report
from datake.config import Settings, load_settings
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
    error: str | None = None


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the Datake API application."""
    runtime = settings or load_settings()
    upload_dir = runtime.project_root / "data" / "api_uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, Path] = {}
    jobs: dict[str, ApiJob] = {}
    lock = Lock()

    app = FastAPI(title="Datake API", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": "0.1.0"}

    @app.post("/files", status_code=201)
    async def upload_file(file: UploadFile = File(...)) -> dict[str, object]:
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
        return {
            "file_id": file_id,
            "filename": filename,
            "size_bytes": len(content),
            "status": "uploaded",
        }

    @app.post("/files/{file_id}/process", status_code=202)
    def process_uploaded_file(file_id: str) -> dict[str, object]:
        source = files.get(file_id)
        if source is None:
            raise HTTPException(status_code=404, detail="File not found")

        job_id = uuid.uuid4().hex
        job = ApiJob(
            job_id=job_id,
            file_id=file_id,
            filename=source.name,
            status="running",
        )
        with lock:
            jobs[job_id] = job

        result = process_file(source, runtime, write_output=True)
        job.result = result
        job.status = "completed" if result.succeeded else "failed"
        job.error = result.error
        if result.succeeded:
            report_path = write_report(
                result,
                runtime,
                hashlib.sha256(source.read_bytes()).hexdigest(),
            )
            job.report_path = report_path
        return _job_payload(job)

    @app.get("/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, object]:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return _job_payload(job)

    @app.get("/jobs/{job_id}/report")
    def get_job_report(job_id: str) -> dict[str, object]:
        job = jobs.get(job_id)
        if job is None or job.report_path is None:
            raise HTTPException(status_code=404, detail="Report not found")
        return json.loads(job.report_path.read_text(encoding="utf-8"))

    @app.get("/files/{file_id}/download")
    def download_file(file_id: str) -> FileResponse:
        source = files.get(file_id)
        if source is None:
            raise HTTPException(status_code=404, detail="File not found")
        job = next((item for item in jobs.values() if item.file_id == file_id), None)
        if job is None or job.result is None or job.result.output_path is None:
            raise HTTPException(status_code=404, detail="Processed file not found")
        return FileResponse(
            job.result.output_path,
            media_type=_media_type(job.result.output_path),
            filename=job.result.output_path.name,
        )

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
