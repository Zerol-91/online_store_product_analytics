"""Profile one source CSV without cleaning it or changing the source file."""

import argparse
import csv
import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
COLUMNS = (
    "event_time", "event_type", "product_id", "category_id", "category_code",
    "brand", "price", "user_id", "user_session",
)
SQL_PATH = ROOT / "sql" / "00_audit" / "profile_events.sql"


def audit_csv(source: Path) -> dict:
    """Scan all rows with explicit string types; count parse failures separately."""
    source = source.resolve()
    if not source.is_file():
        raise FileNotFoundError(
            f"CSV not found: {source}. Extract the Kaggle CSV files into data/raw/."
        )
    if source.suffix.lower() != ".csv":
        raise ValueError("Expected an extracted .csv file, not an archive.")

    before = source.stat()
    with source.open(encoding="utf-8-sig", newline="") as handle:
        header = next(csv.reader(handle), [])
    if header != list(COLUMNS):
        raise ValueError(f"Unexpected CSV header. Expected {list(COLUMNS)}, got {header}.")
    with source.open("rb") as handle:
        checksum = hashlib.file_digest(handle, "sha256").hexdigest()

    with duckdb.connect(config={"memory_limit": "1GB", "threads": "4"}) as connection:
        connection.execute("SET TimeZone = 'UTC'")
        connection.read_csv(
            str(source),
            header=True,
            columns={name: "VARCHAR" for name in COLUMNS},
            auto_detect=False,
            sep=",",
            quotechar='"',
            escapechar='"',
            na_values="",
            strict_mode=True,
            ignore_errors=False,
            null_padding=False,
        ).create_view("raw_events")
        cursor = connection.execute(SQL_PATH.read_text(encoding="utf-8"))
        names = [column[0] for column in cursor.description]
        rows = [dict(zip(names, row)) for row in cursor.fetchall()]

    after = source.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("The source changed during the audit; rerun after extraction finishes.")

    summary = dict(next(row for row in rows if row["is_summary"] == 1))
    summary.pop("is_summary")
    summary.pop("event_type")
    groups = [row for row in rows if row["is_summary"] == 0]
    for row in groups:
        row.pop("is_summary")
    if sum(row["row_count"] for row in groups) != summary["row_count"]:
        raise ValueError("Event-type counts do not reconcile with the total row count.")
    for row in [summary, *groups]:
        for key in ("first_event_utc", "last_event_utc"):
            row[key] = row[key].replace(tzinfo=timezone.utc).isoformat() if row[key] is not None else None

    return {
        "audit_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": {
            "name": source.name,
            "size_bytes": before.st_size,
            "sha256": checksum,
            "columns": list(COLUMNS),
        },
        "runtime": {"python": platform.python_version(), "duckdb": duckdb.__version__},
        "scope": "All rows in one file; no deduplication, exclusions, or business metrics.",
        "summary": summary,
        "by_event_type": groups,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", type=Path, default=ROOT / "data" / "raw" / "2019-Oct.csv",
        help="Extracted CSV to profile (default: data/raw/2019-Oct.csv).",
    )
    parser.add_argument(
        "--output", type=Path,
        help="JSON report (default: data/reports/<input-stem>_audit.json).",
    )
    args = parser.parse_args(argv)
    output = (args.output or ROOT / "data" / "reports" / f"{args.input.stem}_audit.json").resolve()
    if output.suffix.lower() != ".json" or output.is_relative_to(ROOT / "data" / "raw"):
        parser.error("Write JSON reports outside data/raw/; raw files must remain unchanged.")
    if output == args.input.resolve():
        parser.error("The output must not overwrite the input.")
    try:
        report = audit_csv(args.input)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except (OSError, ValueError, duckdb.Error) as error:
        print(f"Audit failed: {error}", file=sys.stderr)
        return 1
    summary = report["summary"]
    print(f"Source: {report['source']['name']}")
    print(f"Rows: {summary['row_count']:,}")
    print(f"UTC range: {summary['first_event_utc']} to {summary['last_event_utc']}")
    print(f"Invalid timestamps: {summary['invalid_event_time']:,}")
    print(f"Invalid prices: {summary['invalid_price']:,}")
    print(f"Zero / negative prices: {summary['zero_price']:,} / {summary['negative_price']:,}")
    print(f"Report: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
