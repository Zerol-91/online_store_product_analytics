"""Build complete-window user journeys and user-clustered cart comparisons."""

import argparse
import json
import sys
import tomllib
from datetime import datetime, timezone
from decimal import Decimal
from importlib.metadata import version
from pathlib import Path

import duckdb

from build_funnel import read_settings
from build_staging import ROOT, SQL_ROOT, query_rows
from segment_statistics import analyze_segments


def prepare_parameters(connection, settings):
    connection.execute("""
        CREATE TEMP TABLE funnel_parameters AS SELECT
            ?::INTEGER AS inactivity_minutes, ?::TIMESTAMP AS observation_start_utc,
            ?::TIMESTAMP AS observation_end_exclusive_utc
    """, [settings["inactivity_minutes"], settings["observation_start_utc"], settings["observation_end_exclusive_utc"]])
    connection.execute("""
        CREATE TEMP TABLE segment_parameters AS SELECT
            ?::INTEGER AS horizon_days, ?::TIMESTAMP AS analysis_start_utc,
            ?::TIMESTAMP AS observation_end_exclusive_utc,
            ?::TIMESTAMP AS price_reference_start_utc,
            ?::TIMESTAMP AS price_reference_end_exclusive_utc,
            ?::VARCHAR AS primary_timestamp_rule
    """, [settings["horizon_days"], settings["analysis_start_utc"], settings["observation_end_exclusive_utc"],
          settings.get("price_reference_start_utc", settings["observation_start_utc"]),
          settings.get("price_reference_end_exclusive_utc", settings["analysis_start_utc"]),
          settings.get("primary_timestamp_rule", "allow_equal")])


def build_user_models(connection):
    connection.execute((SQL_ROOT / "02_marts/users.sql").read_text(encoding="utf-8"))
    connection.execute("""
        CREATE TEMP VIEW funnel_input AS
        SELECT e.user_id, 'user_window' AS user_session, 1::BIGINT AS episode_number,
            e.event_time_utc, e.event_type, e.price
        FROM stg_events e JOIN users u USING (user_id)
        CROSS JOIN segment_parameters p
        WHERE NOT e.is_invalid_user_id AND NOT e.is_invalid_event_time
            AND e.event_time_utc >= u.first_view_utc
            AND e.event_time_utc <= u.first_view_utc + p.horizon_days * INTERVAL '1 day'
    """)
    connection.execute((SQL_ROOT / "02_marts/session_funnel.sql").read_text(encoding="utf-8"))
    connection.execute((SQL_ROOT / "02_marts/user_funnel.sql").read_text(encoding="utf-8"))
    connection.execute((SQL_ROOT / "03_reporting/user_funnel_summary.sql").read_text(encoding="utf-8"))


def validate_user_models(connection):
    coverage = query_rows(connection, """
        SELECT COUNT(*) AS observed_users,
            COUNT(*) FILTER (WHERE first_view_utc IS NULL) AS users_without_view,
            COUNT(*) FILTER (WHERE first_view_utc IS NOT NULL AND NOT has_complete_window)
                AS incomplete_window_users,
            COUNT(*) FILTER (WHERE first_view_utc IS NOT NULL AND NOT enters_after_warmup)
                AS first_view_before_analysis,
            COUNT(*) FILTER (WHERE is_primary_eligible) AS primary_eligible_users,
            COUNT(*) FILTER (WHERE has_complete_window) AS all_mature_first_view_users,
            COUNT(*) FILTER (WHERE is_primary_eligible AND first_seen_utc < first_view_utc)
                AS primary_users_with_earlier_activity,
            COUNT(*) FILTER (WHERE is_primary_eligible AND first_purchase_utc < first_view_utc)
                AS primary_users_with_purchase_before_view
        FROM user_funnel
    """)[0]
    summary = query_rows(connection, "SELECT * FROM user_funnel_summary ORDER BY population, timestamp_rule")
    checks = {
        "user_history_key_unique": connection.execute("SELECT COUNT(*)=COUNT(DISTINCT user_id) FROM users").fetchone()[0],
        "user_key_unique": connection.execute("SELECT COUNT(*)=COUNT(DISTINCT user_id) FROM user_funnel").fetchone()[0],
        "user_required_fields": connection.execute("""
            SELECT COUNT(*)=0 FROM user_funnel
            WHERE user_id IS NULL OR first_seen_utc IS NULL OR has_complete_window IS NULL
                OR enters_after_warmup IS NULL OR is_primary_eligible IS NULL OR has_purchase_in_window IS NULL
        """).fetchone()[0],
        "user_summary_key_unique": connection.execute("SELECT COUNT(*)=COUNT(DISTINCT(population,timestamp_rule)) FROM user_funnel_summary").fetchone()[0],
        "user_history_preserved": connection.execute("SELECT (SELECT COUNT(*) FROM users)=(SELECT COUNT(*) FROM user_funnel)").fetchone()[0],
        "four_user_summary_rows": len(summary) == 4,
        "user_funnel_monotonic": all(0 <= row["full_chain_users"] <= row["cart_users"] <= row["view_users"] for row in summary),
        "user_purchase_coverage": all(row["full_chain_users"] <= row["purchase_users"] <= row["view_users"] for row in summary),
        "user_window_complete": connection.execute("""
            SELECT COUNT(*)=0 FROM user_funnel CROSS JOIN segment_parameters p
            WHERE is_primary_eligible AND (first_view_utc < p.analysis_start_utc
                OR window_end_utc >= p.observation_end_exclusive_utc)
        """).fetchone()[0],
        "user_outcome_deadline": connection.execute("""
            SELECT COUNT(*)=0 FROM user_funnel
            WHERE purchase_after_view_cart_utc > window_end_utc
                OR strict_purchase_after_view_cart_utc > window_end_utc
        """).fetchone()[0],
    }
    return {"coverage": coverage, "summary": summary, "checks": checks}


def build_segment_models(connection, settings):
    for name in ("cart_entry_prices", "price_thresholds", "cart_segments"):
        connection.execute((SQL_ROOT / f"02_marts/{name}.sql").read_text(encoding="utf-8"))
    thresholds = query_rows(connection, "SELECT * FROM price_thresholds")[0]
    for name in ("low_upper", "middle_upper"):
        expected = settings.get("price_" + name)
        if expected is not None and (thresholds[name] is None or Decimal(str(expected)) != Decimal(str(thresholds[name]))):
            raise ValueError(f"Reference price threshold changed: {name}")
    for name in ("cart_segment_users", "cart_segment_summary"):
        connection.execute((SQL_ROOT / f"03_reporting/{name}.sql").read_text(encoding="utf-8"))
    totals = query_rows(connection, """
        SELECT family, SUM(episodes) AS episodes, SUM(conversions) AS conversions,
            SUM(open_episodes) AS open_episodes
        FROM cart_segment_summary GROUP BY family
    """)
    expected = query_rows(connection, """
        SELECT COUNT(*) AS episodes, COUNT(*) FILTER(WHERE converted) AS conversions,
            COUNT(*) FILTER(WHERE open_at_observation_end) AS open_episodes,
            COUNT(entry_price) AS priced_episodes
        FROM cart_segments WHERE is_analysis_period
    """)[0]
    all_cart = connection.execute("SELECT COUNT(*) FROM episodes WHERE cart_event_count>0").fetchone()[0]
    checks = {
        "cart_episode_count": connection.execute("SELECT COUNT(*) FROM cart_entry_prices").fetchone()[0] == all_cart,
        "cart_segment_key_unique": connection.execute("SELECT COUNT(*)=COUNT(DISTINCT(user_id,user_session,episode_number)) FROM cart_segments").fetchone()[0],
        "cart_rows_preserved": connection.execute("SELECT COUNT(*) FROM cart_segments").fetchone()[0] == all_cart,
        "cart_required_fields": connection.execute("""
            SELECT COUNT(*)=0 FROM cart_segments
            WHERE user_id IS NULL OR user_session IS NULL OR episode_number IS NULL
                OR session_start_utc IS NULL OR first_cart_utc IS NULL OR converted IS NULL
                OR visitor_type IS NULL OR price_band IS NULL OR first_seen_utc IS NULL
                OR is_analysis_period IS NULL OR open_at_observation_end IS NULL
        """).fetchone()[0],
        "segment_user_key_unique": connection.execute("SELECT COUNT(*)=COUNT(DISTINCT(family,segment,user_id)) FROM cart_segment_users").fetchone()[0],
        "segment_summary_key_unique": connection.execute("SELECT COUNT(*)=COUNT(DISTINCT(family,segment)) FROM cart_segment_summary").fetchone()[0],
        "segment_user_counts": connection.execute("""
            SELECT COUNT(*)=0 FROM cart_segment_users
            WHERE user_id IS NULL OR family IS NULL OR segment IS NULL OR episodes IS NULL
                OR conversions IS NULL OR open_episodes IS NULL OR episodes<=0
                OR conversions<0 OR conversions>episodes OR open_episodes<0 OR open_episodes>episodes
        """).fetchone()[0],
        "segment_partition_totals": all(all(row[key] == expected[key] for key in ("episodes", "conversions", "open_episodes")) for row in totals),
        "reference_available": expected["priced_episodes"] == 0 or thresholds["reference_priced_episodes"] > 0,
        "visitor_status_uses_past": connection.execute("SELECT COUNT(*)=0 FROM cart_segments WHERE first_seen_utc>session_start_utc").fetchone()[0],
    }
    failures = [name for name, passed in checks.items() if not passed]
    if failures:
        raise ValueError("Segment validation failed: " + ", ".join(failures))
    statistics = analyze_segments(connection, settings["alpha"], settings["planned_comparisons"])
    summary = query_rows(connection, "SELECT * FROM cart_segment_summary ORDER BY family,segment")
    for estimate in statistics["estimates"]:
        row = next(x for x in summary if (x["family"], x["segment"]) == (estimate["family"], estimate["segment"]))
        if (estimate["episodes"], estimate["conversions"], estimate["clusters"]) != (row["episodes"], row["conversions"], row["users"]):
            raise ValueError("Statistical counts do not reconcile with segment summaries.")
    return {"thresholds": thresholds, "summary": summary, "statistics": statistics, "checks": checks}


def build_analysis(database, config=ROOT / "config/analysis.toml", *, include_segments=True):
    database = database.resolve()
    if not database.is_file() or database.suffix != ".duckdb" or database.is_relative_to(ROOT / "data/raw"):
        raise ValueError("Build staging first; use a .duckdb file outside data/raw/.")
    settings = read_settings(config)
    document = tomllib.loads(config.read_text(encoding="utf-8"))
    horizon = document["user_funnel"]["horizon_days"]
    if type(horizon) is not int or horizon <= 0:
        raise ValueError("horizon_days must be a positive integer.")
    entry_start = document.get("analysis", {}).get("start_utc")
    settings.update(horizon_days=horizon, analysis_start_utc=(
        datetime.fromisoformat(entry_start) if entry_start else settings["observation_start_utc"]))
    if not settings["observation_start_utc"] <= settings["analysis_start_utc"] < settings["observation_end_exclusive_utc"]:
        raise ValueError("The analysis entry period must lie within observation.")
    reference = document["price_reference"]
    settings.update(price_reference_start_utc=datetime.fromisoformat(reference["start_utc"]),
                    price_reference_end_exclusive_utc=datetime.fromisoformat(reference["end_exclusive_utc"]),
                    price_low_upper=reference.get("low_upper"), price_middle_upper=reference.get("middle_upper"),
                    alpha=document["inference"]["alpha"], planned_comparisons=document["inference"]["planned_comparisons"])
    if not settings["observation_start_utc"] <= settings["price_reference_start_utc"] < settings["price_reference_end_exclusive_utc"] <= settings["analysis_start_utc"]:
        raise ValueError("Price reference must precede the analysis period.")
    if not 0 < settings["alpha"] < 1 or settings["planned_comparisons"] != 2:
        raise ValueError("Use valid alpha and the two prespecified comparisons.")
    temporary = database.parent / (database.stem + "_tmp")
    temporary.mkdir(exist_ok=True)
    with duckdb.connect(str(database), config={"memory_limit": "1GB", "threads": "2",
            "temp_directory": str(temporary), "preserve_insertion_order": "false"}) as connection:
        fingerprint = str(connection.execute("SELECT BIT_XOR(HASH(t)) FROM stg_events t").fetchone()[0])
        prepare_parameters(connection, settings)
        connection.execute("BEGIN TRANSACTION")
        try:
            print("Building observed-user history and fixed-window journeys...", flush=True)
            build_user_models(connection)
            result = validate_user_models(connection)
            failures = [name for name, passed in result["checks"].items() if not passed]
            if failures:
                raise ValueError("User analysis validation failed: " + ", ".join(failures))
            segment_result = None
            if include_segments:
                print("Building cart segments and user-clustered comparisons...", flush=True)
                segment_result = build_segment_models(connection, settings)
            tables = ["users", "user_funnel", "user_funnel_summary"]
            if include_segments:
                tables.extend(("cart_entry_prices", "price_thresholds", "cart_segments", "cart_segment_users", "cart_segment_summary"))
            fingerprints = {table: str(connection.execute(f"SELECT BIT_XOR(HASH(t)) FROM {table} t").fetchone()[0]) for table in tables}
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
    return {"completed_at_utc": datetime.now(timezone.utc).isoformat(), "settings": settings,
            "runtime": {"python": sys.version.split()[0], "duckdb": duckdb.__version__,
                        "numpy": version("numpy"), "scipy": version("scipy")},
            "staging_fingerprint": fingerprint, "fingerprints": fingerprints,
            "segments": segment_result, **result}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=ROOT / "data/processed/shop.duckdb")
    parser.add_argument("--config", type=Path, default=ROOT / "config/analysis.toml")
    parser.add_argument("--report", type=Path, default=ROOT / "data/reports/user_analysis.json")
    args = parser.parse_args(argv)
    if args.report.suffix != ".json" or args.report.resolve().is_relative_to(ROOT / "data/raw"):
        parser.error("Write JSON reports outside data/raw/.")
    try:
        report = build_analysis(args.database, args.config)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    except (OSError, ValueError, KeyError, duckdb.Error) as error:
        print(f"User analysis failed: {error}", file=sys.stderr)
        return 1
    print(f"Eligible users: {report['coverage']['primary_eligible_users']:,}; report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
