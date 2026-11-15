"""Build session episodes and ordered funnels from validated event staging."""

import argparse
import json
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from build_staging import ROOT, SQL_ROOT, query_rows


def read_settings(path):
    settings = tomllib.loads(path.read_text(encoding="utf-8"))
    gap = settings["sessions"]["inactivity_minutes"]
    if type(gap) is not int or gap != 30:
        raise ValueError("The selected session definition requires inactivity_minutes = 30.")
    rule = settings["funnel"]["primary_timestamp_rule"]
    if rule not in ("allow_equal", "strict"):
        raise ValueError("Unknown timestamp rule.")
    start = datetime.fromisoformat(settings["observation"]["start_utc"])
    end = datetime.fromisoformat(settings["observation"]["end_exclusive_utc"])
    if start.tzinfo is not None or end.tzinfo is not None or start >= end:
        raise ValueError("Use increasing UTC boundaries without timezone suffixes.")
    return {"inactivity_minutes": gap, "primary_timestamp_rule": rule,
            "observation_start_utc": start, "observation_end_exclusive_utc": end}


def validate_funnel(connection):
    eligible = query_rows(connection, """
        SELECT COUNT(*) AS event_count,
            COALESCE(SUM(CASE WHEN event_type='purchase' AND price > 0 THEN price ELSE 0 END), 0)
                AS positive_purchase_value
        FROM stg_events WHERE is_session_eligible
    """)[0]
    mapping = query_rows(connection, """
        SELECT COUNT(*) AS event_count,
            COUNT(DISTINCT (source_file, source_row_number)) AS distinct_keys,
            COUNT(DISTINCT (user_id, user_session, episode_number)) AS episode_count
        FROM episode_events
    """)[0]
    transitions = connection.execute("""
        WITH ordered AS (
            SELECT *, LAG(event_time_utc) OVER w AS previous_time,
                LAG(episode_number) OVER w AS previous_episode
            FROM episode_events
            WINDOW w AS (PARTITION BY user_id, user_session
                ORDER BY event_time_utc, source_file, source_row_number)
        )
        SELECT COUNT(*) FROM ordered CROSS JOIN funnel_parameters p
        WHERE (previous_episode IS NULL AND episode_number != 1)
            OR (event_time_utc - previous_time > p.inactivity_minutes * INTERVAL '1 minute'
                AND episode_number != previous_episode + 1)
            OR (event_time_utc - previous_time <= p.inactivity_minutes * INTERVAL '1 minute'
                AND episode_number != previous_episode)
    """).fetchone()[0]
    totals = query_rows(connection, """
        SELECT session_definition, COUNT(*) AS units, SUM(event_count) AS events,
            SUM(positive_purchase_value) AS positive_purchase_value
        FROM session_funnel GROUP BY session_definition
    """)
    distinct_units = connection.execute("""
        SELECT COUNT(DISTINCT (session_definition, user_id, user_session, episode_number))
        FROM session_funnel
    """).fetchone()[0]
    source_count = connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    checks = {
        "event_mapping_count": mapping["event_count"] == eligible["event_count"],
        "event_mapping_unique": mapping["distinct_keys"] == mapping["event_count"],
        "episode_boundaries": transitions == 0,
        "funnel_keys_unique": distinct_units == sum(row["units"] for row in totals),
        "event_counts_per_definition": all(row["events"] == eligible["event_count"] for row in totals),
        "purchase_values_per_definition": all(row["positive_purchase_value"] == eligible["positive_purchase_value"] for row in totals),
    }
    summary = query_rows(connection, "SELECT * FROM funnel_summary ORDER BY session_definition, timestamp_rule")
    checks["summary_row_count"] = len(summary) == 4
    checks["unit_counts"] = all(row["units"] == (mapping["episode_count"] if row["session_definition"] == "episode_30m" else source_count) for row in summary)
    checks["funnel_monotonic"] = all(0 <= row["full_chain_units"] <= row["view_cart_units"] <= row["view_units"] <= row["units"] for row in summary)
    checks["cart_counts"] = all(row["cart_purchase_units"] + row["abandoned_cart_units"] == row["cart_units"] and row["full_chain_units"] <= row["cart_purchase_units"] for row in summary)
    checks["purchase_coverage"] = all(row["full_chain_units"] + row["purchase_units_without_ordered_chain"] == row["purchase_units"] for row in summary)
    checks["sequence_timestamp_order"] = connection.execute("""
        SELECT COUNT(*) FROM session_funnel
        WHERE (cart_after_view_utc IS NOT NULL
            AND (first_view_utc IS NULL OR cart_after_view_utc < first_view_utc))
            OR (purchase_after_view_cart_utc IS NOT NULL
                AND (cart_after_view_utc IS NULL OR purchase_after_view_cart_utc < cart_after_view_utc))
            OR (strict_cart_after_view_utc IS NOT NULL
                AND (first_view_utc IS NULL OR strict_cart_after_view_utc <= first_view_utc))
            OR (strict_purchase_after_view_cart_utc IS NOT NULL
                AND (strict_cart_after_view_utc IS NULL OR strict_purchase_after_view_cart_utc <= strict_cart_after_view_utc))
    """).fetchone()[0] == 0
    checks["strict_not_larger"] = all(
        strict[field] <= relaxed[field]
        for definition in ("episode_30m", "source_key")
        for relaxed in summary if relaxed["session_definition"] == definition and relaxed["timestamp_rule"] == "allow_equal"
        for strict in summary if strict["session_definition"] == definition and strict["timestamp_rule"] == "strict"
        for field in ("view_cart_units", "full_chain_units", "cart_purchase_units")
    )
    failures = [name for name, passed in checks.items() if not passed]
    if failures:
        raise ValueError("Funnel validation failed: " + ", ".join(failures))
    return {"checks": checks, "summary": summary, "episode_count": mapping["episode_count"]}


def build_funnel(database, config=ROOT / "config/analysis.toml", *, memory_limit="1GB", threads=2):
    database = database.resolve()
    if not database.is_file() or database.suffix != ".duckdb" or database.is_relative_to(ROOT / "data/raw"):
        raise ValueError("Build staging first; use a .duckdb file outside data/raw/.")
    settings = read_settings(config)
    temporary = database.parent / (database.stem + "_tmp")
    temporary.mkdir(exist_ok=True)
    with duckdb.connect(str(database), config={"memory_limit": memory_limit, "threads": str(threads),
            "temp_directory": str(temporary), "preserve_insertion_order": "false"}) as connection:
        bounds = connection.execute("SELECT MIN(event_time_utc), MAX(event_time_utc) FROM stg_events WHERE is_session_eligible").fetchone()
        if bounds[0] is not None and (bounds[0] < settings["observation_start_utc"] or bounds[1] >= settings["observation_end_exclusive_utc"]):
            raise ValueError("Staging timestamps fall outside the configured observation window.")
        fingerprint = str(connection.execute("SELECT BIT_XOR(HASH(t)) FROM stg_events t").fetchone()[0])
        connection.execute("CREATE TEMP TABLE funnel_parameters AS SELECT ?::INTEGER AS inactivity_minutes, ?::TIMESTAMP AS observation_start_utc, ?::TIMESTAMP AS observation_end_exclusive_utc",
                           [settings["inactivity_minutes"], settings["observation_start_utc"], settings["observation_end_exclusive_utc"]])
        connection.execute("BEGIN TRANSACTION")
        try:
            print("Assigning session episodes...", flush=True)
            connection.execute((SQL_ROOT / "02_marts/episode_events.sql").read_text(encoding="utf-8"))
            for index, definition in enumerate(("episode_30m", "source_key")):
                print(f"Building ordered funnel: {definition}...", flush=True)
                episode = "episode_number" if index == 0 else "1::BIGINT"
                connection.execute(f"CREATE OR REPLACE TEMP VIEW funnel_input AS SELECT user_id, user_session, {episode} AS episode_number, event_time_utc, event_type, price FROM episode_events")
                connection.execute((SQL_ROOT / "02_marts/session_funnel.sql").read_text(encoding="utf-8"))
                operation = "CREATE OR REPLACE TABLE session_funnel AS" if index == 0 else "INSERT INTO session_funnel"
                connection.execute(operation + " SELECT ? AS session_definition, * FROM funnel_result", [definition])
            connection.execute("CREATE OR REPLACE VIEW episodes AS SELECT * EXCLUDE(session_definition) FROM session_funnel WHERE session_definition='episode_30m'")
            connection.execute((SQL_ROOT / "03_reporting/funnel_summary.sql").read_text(encoding="utf-8"))
            print("Validating episode and funnel tables...", flush=True)
            result = validate_funnel(connection)
            coverage = query_rows(connection, """
                SELECT COUNT(*) AS staging_events,
                    COUNT(*) FILTER (WHERE NOT is_session_eligible) AS events_excluded_from_sessions,
                    COUNT(*) FILTER (WHERE NOT is_session_eligible AND event_type='purchase') AS purchase_events_excluded,
                    COALESCE(SUM(CASE WHEN NOT is_session_eligible AND event_type='purchase' AND price>0 THEN price ELSE 0 END), 0) AS positive_purchase_value_excluded
                FROM stg_events
            """)[0]
            fingerprints = {table: str(connection.execute(f"SELECT BIT_XOR(HASH(t)) FROM {table} t").fetchone()[0])
                            for table in ("episode_events", "session_funnel", "funnel_summary")}
            sources = query_rows(connection, "SELECT * FROM source_files ORDER BY source_file")
            for table in ("cart_segment_summary", "cart_segment_users", "cart_segments", "price_thresholds", "cart_entry_prices"):
                connection.execute(f"DROP TABLE IF EXISTS {table}")
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
    return {"completed_at_utc": datetime.now(timezone.utc).isoformat(), "settings": settings,
            "runtime": {"python": sys.version.split()[0], "duckdb": duckdb.__version__},
            "staging_fingerprint": fingerprint, "inputs": sources, "coverage": coverage,
            "fingerprints": fingerprints, **result}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=ROOT / "data/processed/shop.duckdb")
    parser.add_argument("--config", type=Path, default=ROOT / "config/analysis.toml")
    parser.add_argument("--report", type=Path, default=ROOT / "data/reports/funnel_build.json")
    args = parser.parse_args(argv)
    if args.report.suffix != ".json" or args.report.resolve().is_relative_to(ROOT / "data/raw"):
        parser.error("Write JSON reports outside data/raw/.")
    try:
        report = build_funnel(args.database, args.config)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    except (OSError, ValueError, KeyError, duckdb.Error) as error:
        print(f"Funnel build failed: {error}", file=sys.stderr)
        return 1
    print(f"Episodes: {report['episode_count']:,}; report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
