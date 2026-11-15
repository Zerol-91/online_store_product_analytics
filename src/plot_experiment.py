"""Export prospective sample-size and conditional-value scenarios."""

import argparse
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault('MPLCONFIGDIR', str(ROOT/'data/processed/mpl_cache'))

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, MaxNLocator


def plot_experiment(report, output):
    if not all(report['checks'].values()) or not all(report['design_checks'].values()):
        raise ValueError('Plot only a validated experiment report.')
    design = report['design']
    if design['status'] != 'planned':
        raise ValueError('A non-boundary mature baseline is required for planning.')
    primary = design['primary']
    rows = [row for row in design['scenarios'] if row['absolute_uplift'] > 0]
    plt.rcParams.update({'font.family':'DejaVu Sans', 'font.size':11, 'text.color':'#0F172A',
                         'axes.labelcolor':'#334155'})
    fig = plt.figure(figsize=(13.6, 6.6))
    left = fig.add_axes([.12, .32, .35, .37])
    right = fig.add_axes([.61, .32, .31, .37], sharey=left)
    mde = design['primary_mde_absolute']*100
    title = f'Plan for +{mde:g} pp: {primary["n_per_group"]:,} users per group'
    fig.text(.04, .96, title, fontsize=17, weight='bold', va='top')
    fig.text(.04, .88,
             f'Historical baseline {design["baseline_conversion"]:.2%} · '
             f'Target under the planning alternative {primary["scenario_conversion"]:.2%} · No experiment has been run',
             fontsize=10, color='#475569')
    left.set_title('Required users per group', loc='left', fontsize=12, pad=25)
    right.set_title('Conditional added purchase-event value', loc='left', fontsize=12, pad=25)
    right.text(0, 1.05, f'Per {design["scenario_population"]:,} eligible users · source price units',
               transform=right.transAxes, fontsize=9, color='#475569')
    maximum_n = max(row['n_per_group'] for row in rows)
    maximum_value = max(row['additional_positive_purchase_value'] for row in rows)
    for y, row in enumerate(rows):
        color = '#B45309' if row['is_primary'] else '#64748B'
        weight = 'bold' if row['is_primary'] else 'normal'
        left.barh(y, row['n_per_group'], height=.48, color=color)
        days = row['replay']['total_days']
        duration = f'{days} days in historical replay' if days is not None else 'Replay unavailable'
        left.text(row['n_per_group']+.025*maximum_n, y,
                  f'{row["n_per_group"]:,}\n{duration}', fontsize=9, va='center',
                  color=color, weight=weight, linespacing=1.5)
        value = row['additional_positive_purchase_value']
        right.barh(y, value, height=.48, color=color)
        right.text(value+.03*maximum_value, y, f'+{value:,.0f}',
                   fontsize=11, va='center', color=color, weight=weight)
    left.set_yticks(range(len(rows)), [f'+{row["absolute_uplift"]*100:g} pp' +
                      ('\nPrimary' if row['is_primary'] else '') for row in rows], fontsize=10)
    left.set_ylim(len(rows)-.5, -.5)
    left.set_xlim(0, maximum_n*1.55)
    right.set_xlim(0, maximum_value*1.30)
    left.set_xlabel('Users per arm · 50/50 allocation', labelpad=12, fontsize=10)
    left.set_ylabel('Assumed absolute conversion uplift', labelpad=13, fontsize=10)
    right.set_xlabel('Additional positive purchase-event value', labelpad=12, fontsize=10)
    right.tick_params(labelleft=False)
    left.xaxis.set_major_formatter(FuncFormatter(lambda x, _: f'{x/1000:g}k' if x else '0'))
    right.xaxis.set_major_formatter(FuncFormatter(lambda x, _: f'{x:,.0f}'))
    for ax in (left, right):
        ax.xaxis.set_major_locator(MaxNLocator(4))
        ax.grid(axis='x', color='#E2E8F0', linewidth=.7)
        ax.set_axisbelow(True)
        ax.tick_params(length=0, pad=8)
        for side in ('top','right','left'):
            ax.spines[side].set_visible(False)
        ax.spines['bottom'].set_color('#CBD5E1')
    fig.text(.04, .17,
             f'Two-sided alpha={design["alpha"]:.2f}; power={design["target_power"]:.0%}. '
             f'Primary study budget: {design["study_budget_days"]} days; amber marks the selected design.',
             fontsize=9, color='#475569')
    conditional = primary['assumed_value_per_converted_user']
    fig.text(.04, .075,
             f'Value scenario assumes unchanged seven-day value per converted user ({conditional:.2f} source units).\n'
             'Durations replay historical unique-user enrollment; complete weeks plus seven-day follow-up, not a traffic forecast.\n'
             'Additional value is conditional event-price arithmetic, not observed uplift, profit, or ROI.\n'
             'Source: eCommerce Events History in Cosmetics Shop · assumptions and fixed-horizon protocol in methodology.',
             fontsize=9, color='#475569', linespacing=1.5, va='center')
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=180, facecolor='white', metadata={'Title':title})
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, default=ROOT/'data/reports/experiment_baseline.json')
    parser.add_argument('--output', type=Path, default=ROOT/'docs/img/experiment_design.png')
    args = parser.parse_args()
    if args.output.suffix.lower() != '.png' or args.output.resolve().is_relative_to(ROOT/'data/raw'):
        parser.error('Export a PNG outside data/raw/.')
    plot_experiment(json.loads(args.report.read_text(encoding='utf-8')), args.output)
    print(f'Saved {args.output}')


if __name__ == '__main__':
    main()
