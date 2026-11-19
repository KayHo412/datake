"""Opt-in notifications for repeatable job outcomes."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from datake.config import Settings

if TYPE_CHECKING:
    from datake.jobs import JobRun


class NotificationError(Exception):
    """Raised when a configured notification cannot be delivered."""


def notify_job_run(
    settings: Settings,
    job_name: str,
    run: JobRun,
    webhook_url: str | None,
    events: tuple[str, ...],
    retries: int,
) -> None:
    """Send a job outcome to a configured webhook when its event is enabled."""
    if not webhook_url or run.status not in events:
        return
    parsed = urlparse(webhook_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise NotificationError("Notification webhook URL must use http:// or https://.")
    if settings.connector_allowed_hosts and parsed.hostname not in (
        settings.connector_allowed_hosts
    ):
        raise NotificationError("Notification webhook host is not approved.")
    payload = {
        "event": f"job.{run.status}",
        "job_name": job_name,
        "status": run.status,
        "attempts": run.attempts,
        "processed_count": run.processed_count,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "error": run.error,
    }
    request = Request(
        webhook_url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": settings.connector_user_agent,
        },
    )
    last_error: str | None = None
    for attempt in range(retries + 1):
        try:
            with urlopen(request, timeout=settings.connector_timeout) as response:
                if not 200 <= response.status < 300:
                    raise NotificationError(
                        f"Notification webhook returned HTTP {response.status}."
                    )
            return
        except HTTPError as exc:
            last_error = f"Notification webhook returned HTTP {exc.code}."
        except URLError as exc:
            last_error = f"Could not deliver notification: {exc.reason}"
        if attempt < retries:
            continue
    raise NotificationError(last_error or "Could not deliver notification.")
