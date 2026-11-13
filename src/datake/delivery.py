"""Deliver cleaned datasets to approved external destinations."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import pandas as pd

from datake.config import Settings

TABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class DeliveryError(Exception):
    """Raised when a destination cannot accept a dataset."""


def write_sqlite(
    dataframe: pd.DataFrame,
    database: Path,
    table: str,
    if_exists: str = "fail",
) -> Path:
    """Write a dataset to a SQLite table."""
    if not TABLE_NAME.fullmatch(table):
        raise DeliveryError(
            "SQLite table must contain only letters, digits, and underscores."
        )
    if if_exists not in {"fail", "replace", "append"}:
        raise DeliveryError("SQLite if_exists must be fail, replace, or append.")
    database = database.expanduser().resolve()
    database.parent.mkdir(parents=True, exist_ok=True)
    try:
        with sqlite3.connect(database) as connection:
            dataframe.to_sql(table, connection, if_exists=if_exists, index=False)
    except (OSError, sqlite3.Error, ValueError) as exc:
        raise DeliveryError(f"Could not write SQLite table: {exc}") from exc
    return database


def post_json(
    dataframe: pd.DataFrame,
    url: str,
    settings: Settings,
) -> int:
    """POST cleaned records to an approved JSON endpoint."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise DeliveryError("Destination URL must use http:// or https://.")
    if settings.connector_allowed_hosts and parsed.hostname not in (
        settings.connector_allowed_hosts
    ):
        raise DeliveryError("Destination host is not approved.")
    payload = dataframe.to_json(orient="records", date_format="iso").encode("utf-8")
    if len(payload) > settings.connector_max_bytes:
        raise DeliveryError("JSON request exceeds the configured response-size limit.")
    request = Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": settings.connector_user_agent,
        },
    )
    try:
        with urlopen(request, timeout=settings.connector_timeout) as response:
            return int(response.status)
    except HTTPError as exc:
        raise DeliveryError(f"Destination returned HTTP {exc.code}.") from exc
    except URLError as exc:
        raise DeliveryError(f"Could not deliver dataset: {exc.reason}") from exc


def write_s3(
    dataframe: pd.DataFrame,
    uri: str,
    settings: Settings,
) -> str:
    """Write a cleaned dataset to S3 using the optional boto3 dependency."""
    try:
        import boto3
    except ImportError as exc:
        raise DeliveryError("S3 output requires the 'connectors' extra.") from exc
    parsed = urlparse(uri)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path:
        raise DeliveryError("S3 destination must look like s3://bucket/key.csv.")
    suffix = Path(parsed.path).suffix.lower()
    if suffix == ".csv":
        body = dataframe.to_csv(index=False).encode("utf-8")
        content_type = "text/csv"
    elif suffix == ".json":
        body = dataframe.to_json(orient="records", indent=2).encode("utf-8")
        content_type = "application/json"
    elif suffix == ".parquet":
        import io

        buffer = io.BytesIO()
        dataframe.to_parquet(buffer, index=False)
        body = buffer.getvalue()
        content_type = "application/vnd.apache.parquet"
    else:
        raise DeliveryError("S3 output must use .csv, .json, or .parquet.")
    if len(body) > settings.connector_max_bytes:
        raise DeliveryError("S3 object exceeds the configured size limit.")
    try:
        boto3.client("s3").put_object(
            Bucket=parsed.netloc,
            Key=parsed.path.lstrip("/"),
            Body=body,
            ContentType=content_type,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        raise DeliveryError(f"Could not write S3 object: {exc}") from exc
    return uri
