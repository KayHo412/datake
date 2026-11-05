"""Command-line interface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from datake.main import read_tabular_file


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
    return parser


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

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
