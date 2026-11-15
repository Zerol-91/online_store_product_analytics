"""Export cart conversion estimates from the validated analysis report."""

import argparse
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "data/processed/mpl_cache"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator, PercentFormatter


def plot_segments(report, output):
    if not all(report["checks"].values()) or not all(report["segments"]["checks"].values()):
        raise ValueError("Plot only a validated analysis report.")
    statistics = report["segments"]["statistics"]
    estimates = {(r["family"], r["segment"]): r for r in statistics["estimates"]}
    contrasts = {r["family"]: r for r in statistics["contrasts"]}
    thresholds = report["segments"]["thresholds"]
    low, middle = (float(thresholds[k]) for k in ("low_upper", "middle_upper"))
    labels = {
        "first_observed": "First observed", "returning": "Returning",
        "low": f"Low (≤ {low:.2f})", "middle": f"Middle ({low:.2f}–{middle:.2f})",
        "high": f"High (> {middle:.2f})", "unknown": "Unknown",
    }
    colors = {"first_observed": "#2563EB", "returning": "#B45309",
              "low": "#2563EB", "middle": "#64748B", "high": "#B45309", "unknown": "#64748B"}
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11,
                         "axes.labelcolor": "#334155", "text.color": "#0F172A"})
    fig, axes = plt.subplots(2, 1, figsize=(11, 8.2), sharex=True,
                             gridspec_kw={"height_ratios": [2, 4]})
    fig.subplots_adjust(left=0.30, right=0.85, top=0.81, bottom=0.23, hspace=0.64)
    price = contrasts["price_band"]
    title = ("High-price entries convert more often than low-price entries"
             if price["ci_low"] is not None and price["ci_low"] > 0
             else "Cart conversion by visitor history and entry price")
    fig.text(0.04, 0.96, title, fontsize=15, weight="bold", va="top")
    start = report["settings"]["analysis_start_utc"][:10]
    end = report["settings"]["observation_end_exclusive_utc"][:10]
    fig.text(0.04, 0.91, f"Cart episodes starting in [{start}, {end}) UTC · Purchase after cart in the same episode",
             fontsize=10, color="#475569")
    largest = max(r["ci_high"] if r["ci_high"] is not None else r["estimate"]
                  for r in estimates.values() if r["estimate"] is not None)
    maximum = max(0.20, largest * 1.15)
    for ax, family, segments, heading in (
        (axes[0], "visitor_type", ("first_observed", "returning"), "Visitor history"),
        (axes[1], "price_band", ("low", "middle", "high", "unknown"), "Entry price · October cutpoints"),
    ):
        ticks = []
        for y, segment in enumerate(segments):
            row = estimates.get((family, segment))
            if row is None:
                ticks.append(f"{labels[segment]}\nNo episodes")
                continue
            ticks.append(f"{labels[segment]}\n{row['episodes']:,} episodes · {row['clusters']:,} users")
            value = row["estimate"]
            error = ([[value - row["ci_low"]], [row["ci_high"] - value]]
                     if row["ci_low"] is not None else None)
            ax.errorbar(value, y, xerr=error, fmt="o", color=colors[segment],
                        markersize=6, capsize=4, elinewidth=1.6)
            ax.text(1.025, y, f"{value:.2%}", transform=ax.get_yaxis_transform(),
                    va="center", fontsize=11, weight="bold", color=colors[segment])
        difference = contrasts[family]["estimate"]
        suffix = f" · {difference * 100:+.2f} pp" if difference is not None else ""
        contrast_label = "Returning − first" if family == "visitor_type" else "High − low"
        ax.set_title(heading, loc="left", fontsize=12, weight="bold", pad=26)
        ax.text(0, 1.07, contrast_label + suffix, transform=ax.transAxes, fontsize=10, color="#475569")
        ax.set_yticks(range(len(segments)), ticks, fontsize=9)
        ax.set_ylim(len(segments) - 0.5, -0.5)
        ax.set_xlim(0, maximum)
        ax.xaxis.set_major_formatter(PercentFormatter(1, decimals=0))
        ax.xaxis.set_major_locator(MultipleLocator(0.05))
        ax.grid(axis="x", color="#E2E8F0", linewidth=0.7)
        ax.set_axisbelow(True)
        ax.tick_params(axis="both", length=0, pad=10)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color("#CBD5E1")
    axes[1].set_xlabel("Episodes with a subsequent purchase / cart episodes", labelpad=12, fontsize=10)
    fig.text(0.04, 0.085,
             "Points: episode conversion. Whiskers: descriptive 95% user-clustered intervals.\n"
             "Entry price: median positive item price at the first cart timestamp; source price units.\n"
             "Users can appear in several groups. Observational comparisons; differences are not causal effects.\n"
             "Source: eCommerce Events History in Cosmetics Shop · see methodology for adjusted contrast intervals.",
             fontsize=9, color="#475569", va="center", linespacing=1.5)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=180, facecolor="white", metadata={"Title": title})
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=ROOT / "data/reports/user_analysis.json")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/img/cart_conversion_by_segment.png")
    args = parser.parse_args()
    if args.output.suffix.lower() != ".png" or args.output.resolve().is_relative_to(ROOT / "data/raw"):
        parser.error("Export a PNG outside data/raw/.")
    plot_segments(json.loads(args.report.read_text(encoding="utf-8")), args.output)
    print(f"Saved {args.output}")


if __name__ == "__main__":
    main()
