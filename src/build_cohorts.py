"""Build observed-purchase histories, complete-window cohorts, and repurchase summaries."""

import argparse
import json
import sys
import tomllib
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import duckdb

from build_funnel import read_settings
from build_staging import ROOT, SQL_ROOT, query_rows
from segment_statistics import cluster_rate

MARTS = ("purchase_events", "purchase_episodes", "buyer_history", "buyer_outcomes",
         "cohort_definitions", "cohort_memberships")
REPORTING = ("cohort_summary", "cohort_curves", "monthly_repurchase")


def cohort_settings(config):
    settings = read_settings(config)
    document = tomllib.loads(config.read_text(encoding="utf-8"))
    settings["analysis_start_utc"] = datetime.fromisoformat(document["analysis"]["start_utc"])
    settings.update(document["repurchase"])
    for name in ("horizons_days", "calendar_month_ages"):
        values = settings[name]
        if not values or any(type(x) is not int or x <= 0 for x in values) or values != sorted(set(values)):
            raise ValueError(f"Use increasing distinct positive integers for {name}.")
    settings["comparison_horizon_days"] = max(settings["horizons_days"])
    start, end = settings["observation_start_utc"], settings["observation_end_exclusive_utc"]
    if not start <= settings["analysis_start_utc"] < end:
        raise ValueError("The analysis period must lie inside observation.")
    cohorts = []
    for item in document["purchase_cohorts"]:
        entry_start = datetime.fromisoformat(item["start_utc"])
        entry_end = datetime.fromisoformat(item["end_exclusive_utc"])
        if not settings["analysis_start_utc"] <= entry_start < entry_end <= end:
            raise ValueError("Configured cohort entry periods must lie inside analysis.")
        if item["family"] not in ("calendar_week", "day_sensitivity") or item["id"].startswith("month_"):
            raise ValueError("Use a configured week/day family and a non-month cohort ID.")
        cohorts.append({"cohort_id": item["id"], "cohort_label": item["label"], "family": item["family"],
                        "entry_start_utc": entry_start, "entry_end_exclusive_utc": entry_end})
    if len({c["cohort_id"] for c in cohorts}) != len(cohorts):
        raise ValueError("Cohort IDs must be unique.")
    weeks = sorted((c for c in cohorts if c["family"] == "calendar_week"), key=lambda c: c["entry_start_utc"])
    if any(a["entry_end_exclusive_utc"] > b["entry_start_utc"] for a, b in zip(weeks, weeks[1:])):
        raise ValueError("Primary weekly cohorts must not overlap.")
    settings["purchase_cohorts"] = cohorts
    return settings


def prepare_parameters(connection, settings):
    connection.execute("""
        CREATE TEMP TABLE cohort_parameters AS SELECT ?::TIMESTAMP AS observation_start_utc,
            ?::TIMESTAMP AS observation_end_exclusive_utc, ?::TIMESTAMP AS analysis_start_utc,
            ?::INTEGER AS comparison_horizon_days
    """, [settings["observation_start_utc"], settings["observation_end_exclusive_utc"],
          settings["analysis_start_utc"], settings["comparison_horizon_days"]])
    connection.execute("CREATE TEMP TABLE repurchase_horizons AS SELECT UNNEST(?::INTEGER[]) AS horizon_days",
                       [settings["horizons_days"]])
    connection.execute("CREATE TEMP TABLE calendar_month_ages AS SELECT UNNEST(?::INTEGER[]) AS month_age",
                       [settings["calendar_month_ages"]])
    connection.execute("""
        CREATE TEMP TABLE configured_purchase_cohorts (
            cohort_id VARCHAR, cohort_label VARCHAR, family VARCHAR,
            entry_start_utc TIMESTAMP, entry_end_exclusive_utc TIMESTAMP)
    """)
    rows = [[c[k] for k in ("cohort_id", "cohort_label", "family", "entry_start_utc", "entry_end_exclusive_utc")]
            for c in settings["purchase_cohorts"]]
    if rows:
        connection.executemany("INSERT INTO configured_purchase_cohorts VALUES (?, ?, ?, ?, ?)", rows)


def build_models(connection):
    for name in MARTS:
        connection.execute((SQL_ROOT / f"02_marts/{name}.sql").read_text(encoding="utf-8"))
    for name in REPORTING:
        connection.execute((SQL_ROOT / f"03_reporting/{name}.sql").read_text(encoding="utf-8"))


def validate_models(c, settings):
    audit = query_rows(c, (SQL_ROOT / "00_audit/profile_purchase_integrity.sql").read_text(encoding="utf-8"))[0]
    keys = {
        "purchase_events": "source_file,source_row_number", "purchase_episodes": "user_id,user_session,episode_number",
        "buyer_history": "user_id", "buyer_outcomes": "user_id,horizon_days", "cohort_definitions": "cohort_id",
        "cohort_memberships": "cohort_id,user_id", "cohort_summary": "cohort_id,horizon_days,population",
        "cohort_curves": "cohort_id,day", "monthly_repurchase": "cohort_id,month_age",
    }
    checks = {f"{table}_key_unique": c.execute(f"SELECT COUNT(*)=COUNT(DISTINCT ({key})) FROM {table}").fetchone()[0]
              for table, key in keys.items()}
    required = {
        "purchase_events": ("source_file", "source_row_number", "user_id", "user_session", "episode_number", "event_time_utc", "positive_purchase_value"),
        "purchase_episodes": ("user_id", "user_session", "episode_number", "first_purchase_utc", "last_purchase_utc", "purchase_event_count"),
        "buyer_history": ("user_id", "first_purchase_utc", "initial_episode_count", "has_overlapping_purchase_episodes"),
        "buyer_outcomes": ("user_id", "horizon_days", "deadline_utc", "has_complete_window", "has_complete_comparison_window"),
        "cohort_definitions": ("cohort_id", "cohort_label", "family", "entry_start_utc", "entry_end_exclusive_utc"),
        "cohort_memberships": ("cohort_id", "user_id"),
        "cohort_summary": ("cohort_id", "horizon_days", "population", "cohort_users", "eligible_users"),
        "cohort_curves": ("cohort_id", "day", "eligible_users"),
        "monthly_repurchase": ("cohort_id", "month_age", "cohort_users", "has_complete_month"),
    }
    checks["required_fields"] = all(c.execute(
        f"SELECT COUNT(*)=0 FROM {table} WHERE " + " OR ".join(f"{col} IS NULL" for col in columns)
    ).fetchone()[0] for table, columns in required.items())
    counts = {table: c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in keys}
    months = c.execute("SELECT COUNT(*) FROM cohort_definitions WHERE family='calendar_month'").fetchone()[0]
    weeks = c.execute("SELECT COUNT(*) FROM cohort_definitions WHERE family='calendar_week'").fetchone()[0]
    checks.update({
        "purchase_source_coverage": audit["uncovered_purchase_events"] == 0 and audit["purchase_events"] == audit["source_purchase_events"],
        "purchase_episode_totals": c.execute("""
            SELECT (SELECT COUNT(*) FROM episodes WHERE purchase_event_count>0)=(SELECT COUNT(*) FROM purchase_episodes)
                AND COALESCE((SELECT SUM(positive_purchase_value) FROM episodes),0)
                    = COALESCE((SELECT SUM(positive_purchase_value) FROM purchase_episodes),0)
        """).fetchone()[0],
        "purchase_event_value_reconciliation": c.execute("""
            SELECT COALESCE((SELECT SUM(positive_purchase_value) FROM purchase_events),0)
                = COALESCE((SELECT SUM(positive_purchase_value) FROM purchase_episodes),0)
        """).fetchone()[0],
        "purchase_event_mapping": counts["purchase_events"] == audit["purchase_events"],
        "buyer_history_source_anchor": c.execute("""
            WITH source AS (SELECT user_id,MIN(event_time_utc) AS first_time FROM stg_events
                WHERE event_type='purchase' AND NOT is_invalid_user_id AND NOT is_invalid_event_time GROUP BY user_id)
            SELECT COUNT(*)=0 FROM source FULL JOIN buyer_history b USING(user_id)
            WHERE source.first_time IS DISTINCT FROM b.first_purchase_utc
        """).fetchone()[0],
        "strict_repeat_order": c.execute("SELECT COUNT(*)=0 FROM buyer_history WHERE first_repeat_utc<=first_purchase_utc").fetchone()[0],
        "outcome_row_count": counts["buyer_outcomes"] == counts["buyer_history"] * len(settings["horizons_days"]),
        "summary_row_count": counts["cohort_summary"] == counts["cohort_definitions"] * len(settings["horizons_days"]) * 3,
        "curve_row_count": counts["cohort_curves"] == weeks * (settings["comparison_horizon_days"] + 1),
        "calendar_row_count": counts["monthly_repurchase"] == months * len(settings["calendar_month_ages"]),
        "immature_outcomes_are_null": c.execute("""
            SELECT COUNT(*)=0 FROM buyer_outcomes WHERE NOT has_complete_window
                AND (repeated IS NOT NULL OR total_positive_purchase_value IS NOT NULL OR repeat_positive_purchase_value IS NOT NULL)
        """).fetchone()[0],
        "complete_outcomes_present": c.execute("""
            SELECT COUNT(*)=0 FROM buyer_outcomes WHERE has_complete_window
                AND (repeated IS NULL OR total_positive_purchase_value IS NULL OR repeat_positive_purchase_value IS NULL
                    OR repeat_positive_purchase_value<0 OR repeat_positive_purchase_value>total_positive_purchase_value)
        """).fetchone()[0],
        "horizon_monotonicity": c.execute("""
            WITH t AS (SELECT *, LAG(repeated::INTEGER) OVER(PARTITION BY user_id ORDER BY horizon_days) AS previous
                FROM buyer_outcomes WHERE has_complete_comparison_window)
            SELECT COUNT(*)=0 FROM t WHERE repeated::INTEGER<previous
        """).fetchone()[0],
        "common_population_consistent": c.execute("""
            SELECT COUNT(*)=0 FROM (SELECT cohort_id,population FROM cohort_summary
                WHERE population<>'horizon_mature' GROUP BY ALL HAVING MIN(eligible_users)<>MAX(eligible_users))
        """).fetchone()[0],
        "cohort_count_bounds": c.execute("""
            SELECT COUNT(*)=0 FROM cohort_summary WHERE eligible_users>cohort_users OR repeat_users>eligible_users
                OR repeat_users<0 OR (eligible_users=0 AND (repeat_rate IS NOT NULL OR repeat_users IS NOT NULL))
        """).fetchone()[0],
        "curve_monotonicity": c.execute("""
            WITH t AS (SELECT *,LAG(repeat_users) OVER(PARTITION BY cohort_id ORDER BY day) AS previous
                FROM cohort_curves) SELECT COUNT(*)=0 FROM t WHERE repeat_users<previous OR repeat_users>eligible_users
        """).fetchone()[0],
        "curve_summary_reconciliation": c.execute("""
            SELECT COUNT(*)=0 FROM cohort_curves c JOIN cohort_summary s ON c.cohort_id=s.cohort_id
                AND c.day=s.horizon_days AND s.population='common_horizon'
            WHERE c.eligible_users<>s.eligible_users OR c.repeat_users IS DISTINCT FROM s.repeat_users
        """).fetchone()[0],
        "incomplete_calendar_cells_are_null": c.execute("""
            SELECT COUNT(*)=0 FROM monthly_repurchase WHERE NOT has_complete_month
                AND (repeat_users IS NOT NULL OR repeat_rate IS NOT NULL)
        """).fetchone()[0],
        "entry_period_membership": c.execute("""
            SELECT COUNT(*)=0 FROM cohort_memberships m JOIN cohort_definitions d USING(cohort_id)
            JOIN buyer_history b USING(user_id)
            WHERE b.first_purchase_utc<d.entry_start_utc OR b.first_purchase_utc>=d.entry_end_exclusive_utc
        """).fetchone()[0],
        "observation_bounds": c.execute("""
            SELECT COUNT(*)=0 FROM episode_events CROSS JOIN cohort_parameters p
            WHERE event_time_utc<p.observation_start_utc OR event_time_utc>=p.observation_end_exclusive_utc
        """).fetchone()[0],
    })
    failures = [key for key, passed in checks.items() if not passed]
    if failures:
        raise ValueError("Cohort validation failed: " + ", ".join(failures))
    return {"audit": audit, "row_counts": counts, "checks": checks}


def describe_rates(summary):
    estimates = []
    for row in summary:
        n, y = row["eligible_users"], row["repeat_users"] or 0
        # One binary outcome per eligible user; its counts determine the interval.
        result = cluster_rate([1] * y + [0] * (n - y), [1] * n)
        if result["estimate"] != row["repeat_rate"]:
            raise ValueError("Rate interval does not reconcile with SQL summary.")
        estimates.append({"cohort_id": row["cohort_id"], "horizon_days": row["horizon_days"],
                          "population": row["population"], **result})
    return estimates


def build_cohorts(database, config=ROOT / "config/analysis.toml"):
    database = database.resolve()
    if not database.is_file() or database.suffix != ".duckdb" or database.is_relative_to(ROOT / "data/raw"):
        raise ValueError("Build staging and session episodes first; use a .duckdb outside data/raw/.")
    settings = cohort_settings(config)
    temporary = database.parent / (database.stem + "_tmp")
    temporary.mkdir(exist_ok=True)
    with duckdb.connect(str(database), config={"memory_limit": "1GB", "threads": "2",
            "temp_directory": str(temporary), "preserve_insertion_order": "false"}) as c:
        upstream_fingerprints = {table: str(c.execute(f"SELECT BIT_XOR(HASH(t)) FROM {table} t").fetchone()[0])
                                 for table in ("stg_events", "episode_events", "session_funnel")}
        prepare_parameters(c, settings)
        c.execute("BEGIN TRANSACTION")
        try:
            print("Building purchase episodes and complete-window cohorts...", flush=True)
            build_models(c)
            result = validate_models(c, settings)
            summary = query_rows(c, "SELECT * FROM cohort_summary ORDER BY family,entry_start_utc,horizon_days,population")
            monthly = query_rows(c, "SELECT * FROM monthly_repurchase ORDER BY entry_start_utc,month_age")
            curves = query_rows(c, "SELECT * FROM cohort_curves ORDER BY cohort_id,day")
            estimates = describe_rates(summary)
            fingerprints = {table: str(c.execute(f"SELECT BIT_XOR(HASH(t)) FROM {table} t").fetchone()[0])
                            for table in MARTS + REPORTING}
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise
    return {"completed_at_utc": datetime.now(timezone.utc).isoformat(), "settings": settings,
            "runtime": {"python": sys.version.split()[0], "duckdb": duckdb.__version__,
                        "numpy": version("numpy"), "scipy": version("scipy")},
            "upstream_fingerprints": upstream_fingerprints, "fingerprints": fingerprints,
            "summary": summary, "monthly_repurchase": monthly, "curves": curves,
            "rate_intervals": estimates, **result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=ROOT / "data/processed/shop.duckdb")
    parser.add_argument("--config", type=Path, default=ROOT / "config/analysis.toml")
    parser.add_argument("--report", type=Path, default=ROOT / "data/reports/cohort_analysis.json")
    args = parser.parse_args()
    if args.report.suffix != ".json" or args.report.resolve().is_relative_to(ROOT / "data/raw"):
        parser.error("Write a JSON report outside data/raw/.")
    try:
        report = build_cohorts(args.database, args.config)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    except (OSError, ValueError, KeyError, duckdb.Error) as error:
        print(f"Cohort build failed: {error}", file=sys.stderr)
        return 1
    print(f"Observed purchasers: {report['audit']['purchasers']:,}; report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
