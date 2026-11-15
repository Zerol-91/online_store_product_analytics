"""Export complete-window repeat curves and calendar-month repurchase cells."""

import argparse
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "data/processed/mpl_cache"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Rectangle
from matplotlib.ticker import MultipleLocator, PercentFormatter


def plot_cohorts(report, output):
    if not report["checks"] or not all(report["checks"].values()):
        raise ValueError("Plot only a validated cohort report.")
    horizon = report["settings"]["comparison_horizon_days"]
    rows = [r for r in report["summary"] if r["family"] == "calendar_week"
            and r["population"] == "common_horizon" and r["horizon_days"] == horizon]
    points = {(r["cohort_id"], r["horizon_days"], r["population"]): r for r in report["rate_intervals"]}
    bf = next((r for r in rows if r["cohort_id"] == "black_friday_week"), None)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "text.color": "#0F172A",
                         "axes.labelcolor": "#334155"})
    fig = plt.figure(figsize=(14.5, 7.4))
    ax = fig.add_axes([0.07, 0.31, 0.43, 0.43])
    heat = fig.add_axes([0.72, 0.31, 0.20, 0.43])
    cax = fig.add_axes([0.94, 0.31, 0.012, 0.43])
    title = (f"Black Friday week: {bf['repeat_rate']:.2%} repeat purchase within {horizon} days"
             if bf is not None and bf["repeat_rate"] is not None else "Observed repeat purchase across cohorts")
    fig.text(0.04, 0.96, title, weight="bold", fontsize=17, va="top")
    end = report["settings"]["observation_end_exclusive_utc"][:10]
    fig.text(0.04, 0.89, f"First observed purchase defines entry · October history retained · UTC observation ends {end}",
             fontsize=10, color="#475569")
    styles = [("#2563EB", "-"), ("#64748B", "--"), ("#B45309", "-"), ("#334155", ":")]
    for index, row in enumerate(rows):
        color, style = styles[index % len(styles)]
        if not row["eligible_users"]:
            continue
        curve = [r for r in report["curves"] if r["cohort_id"] == row["cohort_id"]]
        interval = points[(row["cohort_id"], horizon, "common_horizon")]
        label = f"{row['cohort_label']} · n={row['eligible_users']:,} · {row['repeat_rate']:.2%}"
        ax.plot([r["day"] for r in curve], [r["repeat_rate"] for r in curve],
                label=label, color=color, linestyle=style, linewidth=2.4 if row == bf else 1.8)
        if interval["ci_low"] is not None:
            value = row["repeat_rate"]
            ax.errorbar(horizon, value, yerr=[[value-interval["ci_low"]], [interval["ci_high"]-value]],
                        color=color, fmt="o", markersize=4, capsize=3)
    ax.set_title(f"Cumulative repeat purchase · same {horizon}-day-mature users", loc="left", fontsize=12, pad=18)
    ax.set_xlabel("Elapsed days since first observed purchase", labelpad=10, fontsize=10)
    ax.set_ylabel("Cohort users with another purchasing episode", fontsize=10, labelpad=10)
    ax.set_xlim(0, horizon + 2)
    ax.set_ylim(bottom=0)
    ax.xaxis.set_major_locator(MultipleLocator(15))
    ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    ax.grid(axis="y", color="#E2E8F0", linewidth=0.7)
    ax.set_axisbelow(True)
    ax.tick_params(length=0, pad=7)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("bottom", "left"):
        ax.spines[side].set_color("#CBD5E1")
    ax.legend(loc="upper left", bbox_to_anchor=(-0.01, -0.25), frameon=False, fontsize=9,
              ncol=2, handlelength=2.3, columnspacing=1.4)

    monthly = report["monthly_repurchase"]
    cohorts = list(dict.fromkeys(r["cohort_id"] for r in monthly))
    ages = report["settings"]["calendar_month_ages"]
    lookup = {(r["cohort_id"], r["month_age"]): r for r in monthly}
    values = np.array([[lookup[(cohort, age)]["repeat_rate"] if lookup[(cohort, age)]["repeat_rate"] is not None
                        else np.nan for age in ages] for cohort in cohorts])
    palette = plt.get_cmap("Blues").copy()
    palette.set_bad("#F1F5F9")
    valid = values[np.isfinite(values)]
    upper = max(0.12, float(valid.max())) if valid.size else 0.12
    mesh = heat.imshow(np.ma.masked_invalid(values), cmap=palette, vmin=0, vmax=upper, aspect="auto")
    heat.set_xticks(range(len(ages)), [f"M{age}" for age in ages])
    heat.set_yticks(range(len(cohorts)), [f"{lookup[(c, ages[0])]['cohort_label']}\nn={lookup[(c, ages[0])]['cohort_users']:,}" for c in cohorts], fontsize=10)
    heat.tick_params(length=0, pad=10)
    heat.set_title("Calendar-month repurchase", fontsize=12, pad=18)
    for i, cohort in enumerate(cohorts):
        for j, age in enumerate(ages):
            value = values[i, j]
            if np.isfinite(value):
                text, color = f"{value:.2%}", "white" if value > upper * 0.55 else "#0F172A"
            else:
                text, color = "NA", "#64748B"
                heat.add_patch(Rectangle((j-0.5, i-0.5), 1, 1, fill=False, hatch="///",
                                         edgecolor="#CBD5E1", linewidth=0))
            heat.text(j, i, text, ha="center", va="center", weight="bold", color=color, fontsize=11)
    for spine in heat.spines.values():
        spine.set_visible(False)
    colorbar = fig.colorbar(mesh, cax=cax)
    colorbar.ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    colorbar.ax.tick_params(length=0, labelsize=9)
    colorbar.outline.set_visible(False)
    fig.text(0.67, 0.24, "M1/M2 are separate calendar months,\nnot cumulative 30/60-day windows.\nNA = incomplete follow-up.",
             fontsize=9, color="#475569", linespacing=1.6, va="top")
    fig.text(0.04, 0.075,
             "Left: fixed mature denominators; whiskers show descriptive 95% intervals at the final day only.\n"
             "Repeat requires a different purchasing episode with a strictly later first purchase. No confirmed order IDs.\n"
             "Calendar cohorts are observational; these results do not identify the causal effect or ROI of a promotion.\n"
             "Source: eCommerce Events History in Cosmetics Shop · reproducible cohort tables and definitions in methodology.",
             fontsize=9, color="#475569", linespacing=1.5, va="center")
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=180, facecolor="white", metadata={"Title": title})
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=ROOT / "data/reports/cohort_analysis.json")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/img/repeat_purchase_cohorts.png")
    args = parser.parse_args()
    if args.output.suffix.lower() != ".png" or args.output.resolve().is_relative_to(ROOT / "data/raw"):
        parser.error("Export a PNG outside data/raw/.")
    plot_cohorts(json.loads(args.report.read_text(encoding="utf-8")), args.output)
    print(f"Saved {args.output}")


if __name__ == "__main__":
    main()
