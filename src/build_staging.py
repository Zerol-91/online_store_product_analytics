"""Build source-preserving event staging and diagnostic session aggregates."""

import argparse
import csv
import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from audit_data import COLUMNS, ROOT

SOURCE_NAMES = ("2019-Oct.csv", "2019-Nov.csv", "2019-Dec.csv", "2020-Jan.csv", "2020-Feb.csv")
SQL_ROOT = ROOT / "sql"


def query_rows(connection, sql):
    cursor = connection.execute(sql)
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def validate_build(connection, expected_rows):
    counts = query_rows(connection, """
        SELECT
            COUNT(*) AS row_count,
            COUNT(*) FILTER (WHERE is_session_eligible) AS session_eligible_events,
            COUNT(*) FILTER (WHERE is_invalid_user_id) AS invalid_user_ids,
            COUNT(*) FILTER (WHERE is_invalid_product_id) AS invalid_product_ids,
            COUNT(*) FILTER (WHERE is_invalid_category_id) AS invalid_category_ids,
            COUNT(*) FILTER (WHERE is_missing_user_session) AS missing_session_ids,
            COUNT(*) FILTER (WHERE is_invalid_event_time) AS invalid_event_times,
            COUNT(*) FILTER (WHERE is_invalid_price) AS invalid_prices,
            COUNT(*) FILTER (WHERE is_nonpositive_price) AS nonpositive_prices,
            COUNT(*) FILTER (WHERE is_unknown_event_type) AS unknown_event_types,
            COUNT(*) FILTER (WHERE is_in_duplicate_group) AS rows_in_duplicate_groups
        FROM stg_events
    """)[0]
    raw_count = connection.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0]
    staged_keys = connection.execute("""
        SELECT COUNT(*) FROM (
            SELECT source_file, source_row_number FROM stg_events GROUP BY ALL
        )
    """).fetchone()[0]
    session_keys = connection.execute("""
        SELECT COUNT(*) FROM (SELECT user_id, user_session FROM sessions GROUP BY ALL)
    """).fetchone()[0]
    session_totals = query_rows(connection, """
        SELECT COUNT(*) AS row_count, COALESCE(SUM(event_count), 0) AS event_count,
            COALESCE(SUM(positive_purchase_value), 0) AS positive_purchase_value
        FROM sessions
    """)[0]
    raw_events = query_rows(connection, """
        SELECT event_type, COUNT(*) AS row_count FROM raw_events
        GROUP BY event_type ORDER BY event_type NULLS FIRST
    """)
    staged_events = query_rows(connection, """
        SELECT event_type, COUNT(*) AS row_count FROM stg_events
        GROUP BY event_type ORDER BY event_type NULLS FIRST
    """)
    raw_value = connection.execute("""
        SELECT COALESCE(SUM(TRY_CAST(price AS DECIMAL(24, 6))), 0)
        FROM raw_events
        WHERE event_type = 'purchase' AND TRY_CAST(price AS DECIMAL(24, 6)) > 0
            AND TRY_CAST(price AS DECIMAL(24, 6)) = TRY_CAST(price AS DOUBLE)
    """).fetchone()[0]
    staged_values = query_rows(connection, """
        SELECT
            COALESCE(SUM(CASE WHEN event_type = 'purchase' AND price > 0
                THEN price ELSE 0 END), 0) AS positive_purchase_value,
            COALESCE(SUM(CASE WHEN event_type = 'purchase' AND price > 0
                AND NOT is_session_eligible THEN price ELSE 0 END), 0)
                AS excluded_positive_purchase_value
        FROM stg_events
    """)[0]
    checks = {
        "source_row_count": raw_count == expected_rows,
        "staging_row_count": counts["row_count"] == raw_count,
        "staging_key_unique": staged_keys == counts["row_count"],
        "session_key_unique": session_keys == session_totals["row_count"],
        "session_event_count": session_totals["event_count"] == counts["session_eligible_events"],
        "event_type_counts": raw_events == staged_events,
        "purchase_value_preserved": raw_value == staged_values["positive_purchase_value"],
        "session_purchase_value": raw_value == session_totals["positive_purchase_value"]
            + staged_values["excluded_positive_purchase_value"],
    }
    failures = [name for name, passed in checks.items() if not passed]
    if failures:
        raise ValueError("Build validation failed: " + ", ".join(failures))
    diagnostics = query_rows(connection, (SQL_ROOT / "00_audit/profile_session_integrity.sql").read_text(encoding="utf-8"))[0]
    fingerprints = {
        table: str(connection.execute(f"SELECT BIT_XOR(HASH(t)) FROM {table} AS t").fetchone()[0])
        for table in ("raw_events", "stg_events", "sessions")
    }
    return {"checks": checks, "staging": counts, "sessions": diagnostics,
            "values": staged_values, "event_counts": staged_events, "fingerprints": fingerprints}


def build_staging(inputs: list[Path], database: Path, *, memory_limit="1GB", threads=2):
    inputs = [path.resolve() for path in inputs]
    database = database.resolve()
    if not inputs or len({path.name for path in inputs}) != len(inputs):
        raise ValueError("Provide source files with unique filenames.")
    if database.suffix != ".duckdb" or database.is_relative_to(ROOT / "data/raw"):
        raise ValueError("The database must be a .duckdb file outside data/raw/.")
    manifest = []
    snapshots = []
    for source in inputs:
        if not source.is_file():
            raise FileNotFoundError(f"CSV not found: {source}")
        before = source.stat()
        with source.open(encoding="utf-8-sig", newline="") as handle:
            if next(csv.reader(handle), []) != list(COLUMNS):
                raise ValueError(f"Unexpected CSV header: {source.name}")
        with source.open("rb") as handle:
            checksum = hashlib.file_digest(handle, "sha256").hexdigest()
        snapshots.append((before.st_size, before.st_mtime_ns))
        manifest.append({"source_file": source.name, "size_bytes": before.st_size, "sha256": checksum})
    database.parent.mkdir(parents=True, exist_ok=True)
    temporary_directory = database.parent / (database.stem + "_tmp")
    temporary_directory.mkdir(exist_ok=True)
    started_at = datetime.now(timezone.utc).isoformat()
    with duckdb.connect(str(database), config={
        "memory_limit": memory_limit, "threads": str(threads),
        "temp_directory": str(temporary_directory), "preserve_insertion_order": "true",
    }) as connection:
        connection.execute("SET TimeZone = 'UTC'")
        connection.execute("BEGIN TRANSACTION")
        try:
            for index, source in enumerate(inputs):
                connection.read_csv(
                    str(source), header=True, columns={name: "VARCHAR" for name in COLUMNS},
                    auto_detect=False, sep=",", quotechar='"', escapechar='"', na_values="",
                    strict_mode=True, ignore_errors=False, null_padding=False,
                ).create_view("input_events", replace=True)
                operation = "CREATE OR REPLACE TABLE raw_events AS" if index == 0 else "INSERT INTO raw_events"
                count = connection.execute(operation + """
                    SELECT ? AS source_file, ROW_NUMBER() OVER () AS source_row_number, *
                    FROM input_events
                """, [source.name]).fetchone()[0]
                manifest[index]["row_count"] = count
                print(f"Loaded {source.name}: {count:,} rows", flush=True)
            connection.execute("DROP VIEW input_events")
            print("Building stg_events...", flush=True)
            connection.execute((SQL_ROOT / "01_staging/events.sql").read_text(encoding="utf-8"))
            print("Building sessions...", flush=True)
            connection.execute((SQL_ROOT / "02_marts/sessions.sql").read_text(encoding="utf-8"))
            print("Validating tables...", flush=True)
            result = validate_build(connection, sum(item["row_count"] for item in manifest))
            for source, before in zip(inputs, snapshots):
                after = source.stat()
                if before != (after.st_size, after.st_mtime_ns):
                    raise ValueError(f"Source changed during build: {source.name}")
            connection.execute("CREATE OR REPLACE TABLE source_files (source_file VARCHAR, size_bytes BIGINT, sha256 VARCHAR, row_count BIGINT)")
            connection.executemany("INSERT INTO source_files VALUES (?, ?, ?, ?)",
                [(item["source_file"], item["size_bytes"], item["sha256"], item["row_count"]) for item in manifest])
            connection.execute("DROP VIEW IF EXISTS episodes")
            for table in ("cart_segment_summary", "cart_segment_users", "cart_segments", "price_thresholds", "cart_entry_prices",
                          "user_funnel_summary", "user_funnel", "users",
                          "funnel_summary", "session_funnel", "episode_events"):
                connection.execute(f"DROP TABLE IF EXISTS {table}")
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
    return {
        "started_at_utc": started_at, "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "runtime": {"python": platform.python_version(), "duckdb": duckdb.__version__},
        "inputs": manifest, **result,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=ROOT / "data/raw")
    parser.add_argument("--database", type=Path, default=ROOT / "data/processed/shop.duckdb")
    parser.add_argument("--report", type=Path, default=ROOT / "data/reports/staging_build.json")
    parser.add_argument("--memory-limit", default="1GB")
    parser.add_argument("--threads", type=int, default=2)
    args = parser.parse_args(argv)
    if args.report.suffix != ".json" or args.report.resolve().is_relative_to(ROOT / "data/raw"):
        parser.error("Write JSON reports outside data/raw/.")
    try:
        report = build_staging([args.input_dir / name for name in SOURCE_NAMES], args.database,
                               memory_limit=args.memory_limit, threads=args.threads)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    except (OSError, ValueError, duckdb.Error) as error:
        print(f"Build failed: {error}", file=sys.stderr)
        return 1
    print(f"Events: {report['staging']['row_count']:,}; sessions: {report['sessions']['session_count']:,}")
    print(f"Report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
