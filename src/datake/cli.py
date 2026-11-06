"""Command-line interface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from datake.main import (
    clean_tabular_file,
    merge_tabular_files,
    read_tabular_file,
    validate_tabular_file,
)
from datake.processor import ProcessResult
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
        help="Read a CSV file and print a summary",
    )
    read_parser.add_argument("file", type=Path, help="Path to a CSV file")

    validate_parser = subparsers.add_parser(
        "validate",
        help="Read a CSV file and print a validation report",
    )
    validate_parser.add_argument("file", type=Path, help="Path to a CSV file")

    clean_parser = subparsers.add_parser(
        "clean",
        help="Clean a CSV file and write a copy to data/processed",
    )
    clean_parser.add_argument("file", type=Path, help="Path to a CSV file")

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
        result, summary = validate_tabular_file(args.file, config_path=args.config)
        if not result.succeeded or summary is None:
            print(f"FAILED: {result.error}", file=sys.stderr)
            return 1
        _print_validation(summary)
        return 0 if summary.passed else 1

    if args.command == "clean":
        result = clean_tabular_file(args.file, config_path=args.config)
        _print_process(result)
        return 0 if result.succeeded else 1

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

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
