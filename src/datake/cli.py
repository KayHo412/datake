"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from datake.automation import watch_input
from datake.config import ConfigError, load_settings
from datake.connector import (
    ConnectorError,
    fetch_csv,
    fetch_json,
    fetch_postgres,
    fetch_s3,
    fetch_sftp,
    fetch_sqlite,
)
from datake.delivery import DeliveryError
from datake.history import HistorySummary, ProcessingHistory, ProcessingRun
from datake.jobs import JobStore, run_job, watch_job
from datake.main import (
    clean_tabular_file,
    compare_tabular_files,
    load_runtime,
    merge_tabular_files,
    profile_tabular_file,
    read_tabular_file,
    validate_tabular_file,
)
from datake.processor import ProcessResult
from datake.profiler import ProfileSummary
from datake.validator import ValidationSummary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="datake",
        description="Datake — automated data processing tool",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to settings.json (defaults to config/settings.json)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    read_parser = subparsers.add_parser(
        "read",
        help="Read a supported tabular file and print a summary",
    )
    read_parser.add_argument("file", type=Path, help="Path to a CSV or Excel file")

    validate_parser = subparsers.add_parser(
        "validate",
        help="Read a supported tabular file and print a validation report",
    )
    validate_parser.add_argument(
        "file", type=Path, help="Path to a CSV or Excel file"
    )
    validate_parser.add_argument(
        "--profile", default=None, help="Named validation and cleaning profile"
    )

    profile_parser = subparsers.add_parser(
        "profile",
        help="Summarize a supported tabular file without changing it",
    )
    profile_parser.add_argument(
        "file", type=Path, help="Path to a CSV or Excel file"
    )
    profile_parser.add_argument(
        "--json",
        action="store_true",
        help="Print the profile as JSON",
    )

    clean_parser = subparsers.add_parser(
        "clean",
        help="Clean a supported tabular file using the configured output format",
    )
    clean_parser.add_argument("file", type=Path, help="Path to a CSV or Excel file")
    clean_parser.add_argument(
        "--profile", default=None, help="Named validation and cleaning profile"
    )

    compare_parser = subparsers.add_parser(
        "compare",
        help="Compare two CSV or Excel files without changing them",
    )
    compare_parser.add_argument("before", type=Path, help="Earlier dataset")
    compare_parser.add_argument("after", type=Path, help="Later dataset")
    compare_parser.add_argument(
        "--key",
        action="append",
        dest="keys",
        default=[],
        help="Column used to match rows; repeat for a compound key",
    )
    compare_parser.add_argument("--json", action="store_true", help="Print as JSON")

    merge_parser = subparsers.add_parser(
        "merge",
        help="Clean input files and merge those with matching columns",
    )
    merge_parser.add_argument(
        "files",
        nargs="*",
        type=Path,
        help="Files to merge (defaults to all supported files in data/input)",
    )
    watch_parser = subparsers.add_parser(
        "watch",
        help="Automatically process new files arriving in data/input",
    )
    watch_parser.add_argument(
        "--once",
        action="store_true",
        help="Process the current batch and exit",
    )
    watch_parser.add_argument(
        "--interval",
        type=float,
        default=None,
        help="Polling interval in seconds (default: configured value)",
    )
    watch_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview processing without writing, recording, or moving files",
    )
    watch_parser.add_argument(
        "--profile", default=None, help="Named validation and cleaning profile"
    )
    subparsers.add_parser(
        "profiles",
        help="List named validation and cleaning profiles",
    )
    fetch_parser = subparsers.add_parser(
        "fetch",
        help="Fetch an approved JSON API response into the input directory",
    )
    fetch_parser.add_argument("url", help="Approved HTTP(S) JSON endpoint")
    fetch_parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Destination .json file, usually under data/input",
    )
    csv_parser = subparsers.add_parser(
        "fetch-csv", help="Fetch an approved CSV URL, including published Sheets"
    )
    csv_parser.add_argument("url")
    csv_parser.add_argument("--output", type=Path, required=True)
    sqlite_parser = subparsers.add_parser(
        "fetch-sqlite", help="Run a read-only SQLite query"
    )
    sqlite_parser.add_argument("database", type=Path)
    sqlite_parser.add_argument("query")
    sqlite_parser.add_argument("--output", type=Path, required=True)
    postgres_parser = subparsers.add_parser(
        "fetch-postgres", help="Run a read-only PostgreSQL query"
    )
    postgres_parser.add_argument("connection_url")
    postgres_parser.add_argument("query")
    postgres_parser.add_argument("--output", type=Path, required=True)
    sftp_parser = subparsers.add_parser("fetch-sftp", help="Fetch an SFTP file")
    sftp_parser.add_argument("url")
    sftp_parser.add_argument("--output", type=Path, required=True)
    s3_parser = subparsers.add_parser("fetch-s3", help="Fetch an S3 object")
    s3_parser.add_argument("uri")
    s3_parser.add_argument("--output", type=Path, required=True)
    job_parser = subparsers.add_parser("job", help="Run and control repeatable jobs")
    job_parser.add_argument(
        "action",
        choices=("run", "watch", "cancel", "status"),
        help="Job operation",
    )
    job_parser.add_argument("name", nargs="?", help="Configured job name")
    job_parser.add_argument("--dry-run", action="store_true")
    job_parser.add_argument("--limit", type=int, default=20)
    export_parser = subparsers.add_parser(
        "export",
        help="Clean a file and deliver it to SQLite, HTTP, or S3",
    )
    export_parser.add_argument("file", type=Path)
    export_parser.add_argument("--sqlite", type=Path, default=None)
    export_parser.add_argument("--table", default=None)
    export_parser.add_argument("--endpoint", default=None)
    export_parser.add_argument("--s3", dest="s3_uri", default=None)
    export_parser.add_argument(
        "--if-exists",
        choices=("fail", "replace", "append"),
        default="fail",
    )
    export_parser.add_argument(
        "--profile", default=None, help="Named validation and cleaning profile"
    )
    status_parser = subparsers.add_parser(
        "status",
        help="Show automated processing history",
    )
    status_parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum recent runs to show (default: 10)",
    )
    status_parser.add_argument(
        "--json",
        action="store_true",
        help="Print status as JSON",
    )
    report_parser = subparsers.add_parser(
        "report",
        help="List recorded processing reports",
    )
    report_parser.add_argument(
        "--status",
        choices=("success", "failed"),
        default=None,
        help="Filter reports by outcome",
    )
    report_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum reports to show (default: 20)",
    )
    report_parser.add_argument(
        "--json",
        action="store_true",
        help="Print reports as JSON",
    )
    return parser


def _print_validation(summary: ValidationSummary) -> None:
    print(f"File: {summary.source_path}")
    print(f"Rows: {summary.row_count}")
    print(
        f"Columns ({len(summary.column_names)}): {', '.join(summary.column_names)}"
    )
    print(f"Errors: {summary.error_count}  Warnings: {summary.warning_count}")
    if not summary.issues:
        print("No issues found.")
        return
    print()
    for issue in summary.issues:
        location = f" [{issue.column}]" if issue.column else ""
        print(f"- {issue.severity.upper()} {issue.check}{location}: {issue.message}")
        for example in issue.examples:
            print(f"    example: {example}")


def _print_process(result: ProcessResult) -> None:
    print(f"File: {result.source_path}")
    if not result.succeeded:
        print(f"FAILED: {result.error}")
        return
    assert result.clean_result is not None
    cleaned = result.clean_result
    print(f"Rows in: {cleaned.rows_in}")
    print(f"Rows out: {cleaned.rows_out}")
    print(f"Columns: {', '.join(cleaned.column_names)}")
    if result.output_path:
        print(f"Wrote: {result.output_path}")
    if cleaned.actions:
        print()
        for action in cleaned.actions:
            print(f"- {action}")
    assert result.dataframe is not None
    if not result.dataframe.empty:
        print()
        print(result.dataframe.to_string(index=False))


def _print_status(summary: HistorySummary) -> None:
    """Print a history summary."""
    print(f"Total runs: {summary.total}")
    print(f"Successful: {summary.successful}")
    print(f"Failed: {summary.failed}")
    if not summary.recent_runs:
        print("No processing runs recorded.")
        return
    print()
    print("Recent runs:")
    for run in summary.recent_runs:
        completed = run.completed_at or "in progress"
        print(f"- {run.status.upper()} {run.source_path} ({completed})")
        if run.error:
            print(f"  error: {run.error}")


def _status_payload(summary: HistorySummary) -> dict[str, object]:
    return {
        "total": summary.total,
        "successful": summary.successful,
        "failed": summary.failed,
        "recent_runs": [
            {
                "source_path": str(run.source_path),
                "file_hash": run.file_hash,
                "status": run.status,
                "completed_at": run.completed_at,
                "report_path": str(run.report_path) if run.report_path else None,
                "error": run.error,
            }
            for run in summary.recent_runs
        ],
    }


def _run_payload(run: ProcessingRun) -> dict[str, object]:
    return {
        "source_path": str(run.source_path),
        "file_hash": run.file_hash,
        "status": run.status,
        "completed_at": run.completed_at,
        "report_path": str(run.report_path) if run.report_path else None,
        "error": run.error,
    }


def _print_profile(path: Path, profile: ProfileSummary) -> None:
    print(f"File: {path}")
    print(f"Rows: {profile.row_count}")
    print(f"Columns: {profile.column_count}")
    print(f"Duplicate rows: {profile.duplicate_rows}")
    print(f"Quality score: {profile.quality_score}/100")
    print()
    for column in profile.columns:
        print(f"- {column.name}")
        print(f"  type: {column.data_type}")
        print(
            f"  missing: {column.missing_count} "
            f"({column.missing_percent:.2f}%)"
        )
        print(f"  unique values: {column.unique_count}")
        if column.minimum is not None:
            print(f"  range: {column.minimum} to {column.maximum}")
        if column.top_values:
            values = ", ".join(
                f"{item['value']} ({item['count']})" for item in column.top_values
            )
            print(f"  common values: {values}")
        if column.unusual_count:
            values = ", ".join(str(value) for value in column.unusual_values)
            print(f"  unusual values: {column.unusual_count} ({values})")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "read":
        result = read_tabular_file(args.file, config_path=args.config)
        if not result.succeeded:
            print(f"FAILED: {result.error}", file=sys.stderr)
            return 1

        print(f"File: {result.source_path}")
        print(f"Rows: {result.row_count}")
        print(f"Columns ({len(result.column_names)}): {', '.join(result.column_names)}")
        assert result.dataframe is not None
        print()
        print(result.dataframe.head().to_string(index=False))
        return 0

    if args.command == "validate":
        try:
            result, summary = validate_tabular_file(
                args.file,
                config_path=args.config,
                profile=args.profile,
            )
        except ConfigError as exc:
            print(f"FAILED: {exc}", file=sys.stderr)
            return 1
        if not result.succeeded or summary is None:
            print(f"FAILED: {result.error}", file=sys.stderr)
            return 1
        _print_validation(summary)
        return 0 if summary.passed else 1

    if args.command == "profile":
        result, profile = profile_tabular_file(args.file, config_path=args.config)
        if not result.succeeded or profile is None:
            print(f"FAILED: {result.error}", file=sys.stderr)
            return 1
        if args.json:
            payload = {"source_path": str(result.source_path), **profile.to_dict()}
            print(json.dumps(payload, indent=2))
        else:
            _print_profile(result.source_path, profile)
        return 0

    if args.command == "clean":
        try:
            result = clean_tabular_file(
                args.file,
                config_path=args.config,
                profile=args.profile,
            )
        except ConfigError as exc:
            print(f"FAILED: {exc}", file=sys.stderr)
            return 1
        _print_process(result)
        return 0 if result.succeeded else 1

    if args.command == "compare":
        try:
            before, after, summary = compare_tabular_files(
                args.before,
                args.after,
                key_columns=args.keys or None,
                config_path=args.config,
            )
        except ValueError as exc:
            print(f"FAILED: {exc}", file=sys.stderr)
            return 1
        if not before.succeeded:
            print(f"FAILED: {before.error}", file=sys.stderr)
            return 1
        if not after.succeeded:
            print(f"FAILED: {after.error}", file=sys.stderr)
            return 1
        assert summary is not None
        if args.json:
            print(json.dumps(summary.to_dict(), indent=2))
        else:
            print(f"Added rows: {summary.added_count}")
            print(f"Removed rows: {summary.removed_count}")
            print(f"Changed rows: {summary.changed_count}")
        return 0

    if args.command == "merge":
        results, merged_path = merge_tabular_files(
            list(args.files) or None,
            config_path=args.config,
        )
        if not results:
            print("No files to merge.", file=sys.stderr)
            return 1
        failures = 0
        for result in results:
            _print_process(result)
            print()
            if not result.succeeded:
                failures += 1
        if merged_path:
            print(f"Merged output: {merged_path}")
        elif failures < len(results):
            print("No compatible files to merge (columns did not match).")
        return 1 if failures == len(results) else 0

    if args.command == "watch":
        try:
            settings = load_runtime(args.config, profile=args.profile)
        except ConfigError as exc:
            print(f"FAILED: {exc}", file=sys.stderr)
            return 1
        try:
            watch_input(
                settings,
                once=args.once,
                interval=args.interval,
                dry_run=args.dry_run,
            )
        except KeyboardInterrupt:
            print("Watch stopped.")
        return 0

    if args.command == "profiles":
        try:
            settings = load_settings(args.config)
        except ConfigError as exc:
            print(f"FAILED: {exc}", file=sys.stderr)
            return 1
        if not settings.available_profiles:
            print("No named profiles configured.")
        else:
            for profile in settings.available_profiles:
                print(profile)
        return 0

    if args.command == "fetch":
        try:
            settings = load_settings(args.config)
            path = fetch_json(args.url, args.output, settings)
        except (ConfigError, ConnectorError) as exc:
            print(f"FAILED: {exc}", file=sys.stderr)
            return 1
        print(f"Fetched: {path}")
        return 0

    if args.command in {
        "fetch-csv",
        "fetch-sqlite",
        "fetch-postgres",
        "fetch-sftp",
        "fetch-s3",
    }:
        try:
            settings = load_settings(args.config)
            if args.command == "fetch-csv":
                path = fetch_csv(args.url, args.output, settings)
            elif args.command == "fetch-sqlite":
                path = fetch_sqlite(args.database, args.query, args.output)
            elif args.command == "fetch-postgres":
                path = fetch_postgres(
                    args.connection_url,
                    args.query,
                    args.output,
                )
            elif args.command == "fetch-sftp":
                path = fetch_sftp(args.url, args.output, settings)
            else:
                path = fetch_s3(args.uri, args.output, settings)
        except (ConfigError, ConnectorError) as exc:
            print(f"FAILED: {exc}", file=sys.stderr)
            return 1
        print(f"Fetched: {path}")
        return 0

    if args.command == "export":
        from datake.main import deliver_tabular_file

        try:
            result, destination = deliver_tabular_file(
                args.file,
                sqlite_path=args.sqlite,
                table=args.table,
                endpoint=args.endpoint,
                s3_uri=args.s3_uri,
                if_exists=args.if_exists,
                config_path=args.config,
                profile=args.profile,
            )
        except (ConfigError, DeliveryError) as exc:
            print(f"FAILED: {exc}", file=sys.stderr)
            return 1
        if not result.succeeded:
            print(f"FAILED: {result.error}", file=sys.stderr)
            return 1
        print(f"Delivered: {destination}")
        return 0

    if args.command == "job":
        try:
            settings = load_runtime(args.config)
            if args.action == "status":
                runs = JobStore(settings).runs(args.name, args.limit)
                for run in runs:
                    print(
                        f"{run.job_name} {run.status.upper()} "
                        f"attempts={run.attempts} processed={run.processed_count} "
                        f"{run.completed_at}"
                    )
                if not runs:
                    print("No job runs recorded.")
                return 0
            if not args.name:
                parser.error("job run/watch/cancel requires a job name")
            if args.action == "cancel":
                JobStore(settings).cancel(args.name)
                print(f"Cancelled: {args.name}")
                return 0
            if args.action == "run":
                JobStore(settings).reset_cancelled(args.name)
                run = run_job(settings, args.name, dry_run=args.dry_run)
                print(
                    f"{run.job_name}: {run.status} "
                    f"processed={run.processed_count} attempts={run.attempts}"
                )
                return 0 if run.status == "success" else 1
            try:
                JobStore(settings).reset_cancelled(args.name)
                watch_job(settings, args.name, dry_run=args.dry_run)
            except KeyboardInterrupt:
                JobStore(settings).cancel(args.name)
                print(f"Cancelled: {args.name}")
            return 0
        except (ConfigError, ValueError) as exc:
            print(f"FAILED: {exc}", file=sys.stderr)
            return 1

    if args.command == "status":
        if args.limit < 0:
            parser.error("--limit must be non-negative")
        settings = load_runtime(args.config)
        summary = ProcessingHistory(settings).summary(limit=args.limit)
        if args.json:
            print(json.dumps(_status_payload(summary), indent=2))
        else:
            _print_status(summary)
        return 0

    if args.command == "report":
        if args.limit < 0:
            parser.error("--limit must be non-negative")
        settings = load_runtime(args.config)
        runs = ProcessingHistory(settings).runs(
            status=args.status,
            limit=args.limit,
        )
        if args.json:
            print(json.dumps([_run_payload(run) for run in runs], indent=2))
        else:
            if not runs:
                print("No matching reports.")
            for run in runs:
                print(f"{run.status.upper()} {run.source_path}")
                print(f"  hash: {run.file_hash}")
                print(f"  completed: {run.completed_at or 'in progress'}")
                if run.report_path:
                    print(f"  report: {run.report_path}")
                if run.error:
                    print(f"  error: {run.error}")
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
