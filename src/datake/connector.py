"""Safe connectors for approved remote tabular sources."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import pandas as pd

from datake.config import Settings


class ConnectorError(Exception):
    """Raised when a remote source cannot be safely collected."""


def fetch_json(
    url: str,
    destination: Path,
    settings: Settings,
) -> Path:
    """Fetch a JSON API response and save it as a Datake JSON input file.

    Only explicitly allowed hosts are fetched. The response must contain a
    list of records or a list under ``data``, ``results``, or ``items``.
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConnectorError("URL must use http:// or https://.")
    if settings.connector_allowed_hosts and parsed.hostname not in (
        settings.connector_allowed_hosts
    ):
        allowed = ", ".join(settings.connector_allowed_hosts)
        raise ConnectorError(f"Host is not approved. Allowed hosts: {allowed}")

    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": settings.connector_user_agent,
        },
    )
    try:
        with urlopen(request, timeout=settings.connector_timeout) as response:
            content_type = response.headers.get_content_type()
            if content_type not in {"application/json", "text/json"}:
                raise ConnectorError(
                    f"Expected JSON response, received {content_type!r}."
                )
            body = _read_limited(response, settings.connector_max_bytes)
    except HTTPError as exc:
        raise ConnectorError(f"Remote server returned HTTP {exc.code}.") from exc
    except URLError as exc:
        raise ConnectorError(f"Could not fetch URL: {exc.reason}") from exc

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ConnectorError(f"Response was not valid JSON: {exc}") from exc
    records = _records_from_payload(payload)
    destination = destination.expanduser().resolve()
    if destination.suffix.lower() != ".json":
        raise ConnectorError("Fetch destination must use the .json extension.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(records, indent=2), encoding="utf-8")
    return destination


def fetch_csv(url: str, destination: Path, settings: Settings) -> Path:
    """Fetch an approved CSV URL, including a published Google Sheet."""
    body = _fetch_http(url, settings, {"text/csv", "text/plain"})
    destination = _destination(destination, ".csv")
    destination.write_bytes(body)
    return destination


def fetch_sqlite(database: Path, query: str, destination: Path) -> Path:
    """Run a read-only query against SQLite and save its result."""
    if not database.is_file():
        raise ConnectorError(f"SQLite database not found: {database}")
    try:
        connection_uri = f"file:{database.resolve()}?mode=ro"
        with sqlite3.connect(connection_uri, uri=True) as connection:
            dataframe = pd.read_sql_query(query, connection)
    except (OSError, sqlite3.Error, ValueError) as exc:
        raise ConnectorError(f"Could not query SQLite database: {exc}") from exc
    return _write_dataframe(dataframe, destination)


def fetch_postgres(
    connection_url: str,
    query: str,
    destination: Path,
) -> Path:
    """Run a read-only PostgreSQL query using the optional psycopg package."""
    try:
        import psycopg
    except ImportError as exc:
        raise ConnectorError(
            "PostgreSQL support requires the 'connectors' extra."
        ) from exc
    try:
        options = "-c default_transaction_read_only=on"
        with psycopg.connect(connection_url, options=options) as connection:
            with connection.cursor() as cursor:
                cursor.execute(query)
                rows = cursor.fetchall()
                columns = [item.name for item in cursor.description]
        return _write_dataframe(pd.DataFrame(rows, columns=columns), destination)
    except (OSError, ValueError, RuntimeError) as exc:
        raise ConnectorError(f"Could not query PostgreSQL: {exc}") from exc


def fetch_sftp(url: str, destination: Path, settings: Settings) -> Path:
    """Copy an approved SFTP file using credentials supplied by the environment."""
    try:
        import paramiko
    except ImportError as exc:
        raise ConnectorError("SFTP support requires the 'connectors' extra.") from exc
    parsed = urlparse(url)
    if parsed.scheme != "sftp" or not parsed.hostname or not parsed.path:
        raise ConnectorError("SFTP URL must look like sftp://host/path.")
    if settings.connector_allowed_hosts and parsed.hostname not in (
        settings.connector_allowed_hosts
    ):
        raise ConnectorError("SFTP host is not approved.")
    username = os.environ.get("DATAKE_SFTP_USERNAME")
    if not username:
        raise ConnectorError("Set DATAKE_SFTP_USERNAME for SFTP access.")
    try:
        client = paramiko.SSHClient()
        client.load_system_host_keys()
        client.connect(
            parsed.hostname,
            username=username,
            timeout=settings.connector_timeout,
        )
        with client.open_sftp() as sftp:
            body = sftp.open(parsed.path, "rb").read(settings.connector_max_bytes + 1)
        client.close()
    except (OSError, ValueError, RuntimeError) as exc:
        raise ConnectorError(f"Could not fetch SFTP file: {exc}") from exc
    if len(body) > settings.connector_max_bytes:
        raise ConnectorError("SFTP response exceeds the configured limit.")
    destination = _destination(destination, Path(parsed.path).suffix or ".csv")
    destination.write_bytes(body)
    return destination


def fetch_s3(uri: str, destination: Path, settings: Settings) -> Path:
    """Copy an S3 object using optional boto3 and environment credentials."""
    try:
        import boto3
    except ImportError as exc:
        raise ConnectorError("S3 support requires the 'connectors' extra.") from exc
    parsed = urlparse(uri)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path:
        raise ConnectorError("S3 URL must look like s3://bucket/key.")
    try:
        body = boto3.client("s3").get_object(
            Bucket=parsed.netloc,
            Key=parsed.path.lstrip("/"),
        )["Body"].read(settings.connector_max_bytes + 1)
    except (OSError, ValueError, RuntimeError) as exc:
        raise ConnectorError(f"Could not fetch S3 object: {exc}") from exc
    if len(body) > settings.connector_max_bytes:
        raise ConnectorError("S3 object exceeds the configured limit.")
    destination = _destination(destination, Path(parsed.path).suffix or ".csv")
    destination.write_bytes(body)
    return destination


def _read_limited(response: object, maximum: int) -> str:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = response.read(min(64 * 1024, maximum - total + 1))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > maximum:
            raise ConnectorError(
                f"Response exceeds the configured limit of {maximum} bytes."
            )
    return b"".join(chunks).decode("utf-8")


def _fetch_http(
    url: str,
    settings: Settings,
    content_types: set[str],
) -> bytes:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConnectorError("URL must use http:// or https://.")
    if settings.connector_allowed_hosts and parsed.hostname not in (
        settings.connector_allowed_hosts
    ):
        raise ConnectorError("Host is not approved.")
    try:
        request = Request(url, headers={"User-Agent": settings.connector_user_agent})
        with urlopen(request, timeout=settings.connector_timeout) as response:
            content_type = response.headers.get_content_type()
            if content_type not in content_types:
                raise ConnectorError(f"Unexpected response type: {content_type!r}.")
            return _read_limited_bytes(response, settings.connector_max_bytes)
    except (HTTPError, URLError) as exc:
        raise ConnectorError(f"Could not fetch URL: {exc}") from exc


def _read_limited_bytes(response: object, maximum: int) -> bytes:
    body = response.read(maximum + 1)
    if len(body) > maximum:
        raise ConnectorError(
            f"Response exceeds the configured limit of {maximum} bytes."
        )
    return body


def _destination(path: Path, suffix: str) -> Path:
    destination = path.expanduser().resolve()
    if destination.suffix.lower() != suffix:
        raise ConnectorError(f"Destination must use the {suffix} extension.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    return destination


def _write_dataframe(dataframe: pd.DataFrame, destination: Path) -> Path:
    destination = destination.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.suffix == ".csv":
        dataframe.to_csv(destination, index=False)
    elif destination.suffix == ".json":
        dataframe.to_json(destination, orient="records", indent=2)
    elif destination.suffix == ".parquet":
        dataframe.to_parquet(destination, index=False)
    else:
        raise ConnectorError("Database destination must be .csv, .json, or .parquet.")
    return destination


def _records_from_payload(payload: object) -> list[dict[str, object]]:
    if isinstance(payload, list):
        records = payload
    elif isinstance(payload, dict):
        records = next(
            (payload[key] for key in ("data", "results", "items") if key in payload),
            None,
        )
    else:
        records = None
    if not isinstance(records, list) or not all(
        isinstance(record, dict) for record in records
    ):
        raise ConnectorError(
            "JSON response must be an array of objects or contain one under "
            "'data', 'results', or 'items'."
        )
    return records
