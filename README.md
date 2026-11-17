# From Cart to Repeat Purchase

Product analytics of a cosmetics store: **20.7 million events**, October 2019–February 2020. The project examines where recorded purchase journeys end, how cart conversion differs across segments, and whether Black Friday week buyers return.

**Main finding:** 122,189 of 1,049,303 cart episodes contain a subsequent purchase — **11.64%**. This measures completion within an observed episode; it does not mean the remaining customers never buy later.

**Proposed next step:** investigate cost and fulfillment uncertainty, then test showing that information in the cart. The source does not identify why users leave; no experiment has been run.

## Findings

### 1. The ordered funnel does not cover every purchase

An episode is a `(user_id, user_session)` group split at inactivity gaps **greater than 30 minutes**. The main sequence allows equal timestamps and can involve different products.

| Ordered stage, October–February | Episodes | Conversion from previous stage |
|---|---:|---:|
| Recorded view | 4,501,112 | — |
| Cart at/after a view | 745,696 | 16.57% |
| Purchase at/after that cart | 95,850 | 12.85% |

The **11.64% all-cart conversion** has a broader denominator than the ordered funnel: it includes cart episodes without a prior view. Among 157,595 purchase-containing episodes, 61,745 (**39.18%**) lack the full recorded chain. Missing steps describe coverage; they do not establish tracking faults or customer motives.

![Observed episode conversion, ordered funnel, and coverage of purchase-containing episodes](docs/img/dashboard_overview.png)

### 2. Higher entry prices coincide with higher cart conversion

The segment analysis covers **807,560 cart episodes entering November–February**. Visitor history includes October. Entry price uses positive prices of unique products at the first cart timestamp; October-only terciles freeze the boundaries at **3.00** and **6.03** source units. Missing positive entry prices remain Unknown.

![Cart conversion by observed visitor history and frozen price bands, with descriptive user-clustered 95% intervals](docs/img/cart_conversion_by_segment.png)

| Prespecified comparison | Conversion rates | Difference | Adjusted 97.5% interval |
|---|---|---:|---:|
| Returning − first observed | 12.04% vs 13.01% | −0.97 pp | [−1.19, −0.75] pp |
| High − low entry price | 14.95% vs 10.66% | +4.30 pp | [+4.07, +4.53] pp |

Intervals account for repeated episodes and users appearing in both groups; Bonferroni correction covers the two planned comparisons. These are **observational associations**: raising prices is not shown to improve conversion, and lower returning-episode conversion does not explain why people leave.

### 3. Black Friday week buyers repeat less than the preceding November cohorts

A repeat requires a **different purchasing episode beginning strictly after the first observed purchase**. Multiple product rows in the initial episode are not repeat orders. October buyers do not re-enter later first-purchase cohorts.

Both horizons below use the **same users with complete 60-day follow-up**.

| First observed purchase | Buyers | Repeat by day 30 | Repeat by day 60 |
|---|---:|---:|---:|
| Nov 11–17 | 5,056 | 15.59% | 21.04% |
| Nov 18–24 | 7,894 | 13.19% | 18.76% |
| **Nov 25–Dec 1: Black Friday week** | **6,415** | **12.46%** | **17.97%** |
| Dec 2–8 | 4,520 | 10.46% | 16.68% |

![Cumulative repeat purchase on fixed mature populations and calendar M1/M2 repurchasing, with unavailable follow-up marked NA](docs/img/repeat_purchase_cohorts.png)

The BF-week 60-day rate is below both preceding weeks and above the following week; its descriptive 95% interval is **17.03%–18.91%**. Calendar M1/M2 measure purchases in separate later calendar months, not cumulative 30/60-day outcomes. Incomplete cells remain NA.

These calendar cohorts are not verified promotion exposures. Customer mix, seasonality, unknown discounts, and missing costs prevent conclusions about the promotion's causal effect, ROI, or displacement of December demand.

## Proposed experiment

**Hypothesis:** showing complete cost and available fulfillment terms in the cart, without a discount, may reduce uncertainty and increase purchase conversion. Confirm the current interface and investigate abandonment reasons before committing to this intervention.

The historical planning baseline enrolls each user once at their first eligible cart in November–February, including users with October history. Among **277,852 users with complete seven-day windows**, 72,498 purchase: **26.09%**. This is a user-level post-cart outcome, distinct from the episode funnel and the first-view user funnel.

| Planning input | Selected design |
|---|---|
| Assignment | Stable user-level randomization, 50/50; analyze all eligible assigned users |
| Primary outcome | Any purchase within seven days of inclusion |
| MDE | **+1 percentage point**, from 26.09% to 27.09% |
| Error rate and power | Two-sided alpha 0.05; power 0.80 |
| Required sample | **30,643 users per arm**, 61,286 total |
| Historical duration | **21 enrollment + 7 follow-up days** |

The MDE is justified by the selected four-week study budget and historical eligible traffic, **not by an estimated profitability threshold**. Future traffic must be checked. Fix enrollment and follow-up before launch; use a single final readout. Assignment/exposure events and checkout-error, latency, and cancellation/refund guardrails still need instrumentation.

**Conditional value scenario:** at an assumed +1 pp uplift and unchanged seven-day positive purchase-event value per converted user:

`10,000 eligible users × 0.01 uplift × 39.6574 value per converted user = 3,965.74 source units`

The conditional mean can include several purchasing episodes; it is not average order value. This is neither a forecast of treatment effect nor realized revenue or profit. [Sample-size and value sensitivity](docs/img/experiment_design.png) and the [prospective protocol](docs/methodology.md#prospective-protocol-and-conditional-value-scenarios) document the alternatives and assumptions.

## Data and analytical choices

Source: [eCommerce Events History in Cosmetics Shop](https://www.kaggle.com/datasets/mkechinov/ecommerce-events-history-in-cosmetics-shop), Michael Kechinov / REES46. Five CSV files contain **20,692,840 events across 152 calendar days**. Raw data is not included; dataset terms remain those specified by the publisher.

- **Preserve evidence:** retain all rows with quality/duplicate flags. Removing exact purchase copies changes the positive purchase-price sum by only **0.0561%**; quantity is unknown, so duplicates are retained in the primary analysis.
- **Respect sequence and history:** search for an ordered chain; compare strict timestamp ordering and original source-session keys as sensitivity. “First” means first observed, with October as lookback.
- **Respect follow-up:** exclude immature users from fixed-window denominators; retain NULL outcomes. Sessionless events stay in user history, while episode analysis requires a session token.
- **Limit monetary claims:** there is no order ID, confirmed quantity, verified currency, cost, or refund history. Purchase episodes are proxies; positive event-price sums are not profit or confirmed net sales.

[Methodology](docs/methodology.md) defines populations, windows, clustering, sensitivity checks, and source limitations. A separate seven-day first-view user funnel is implemented there; its entry and denominator differ from the experimental baseline.

## Dashboard and implementation

The local Metabase dashboard contains **14 SQL questions**, covering the funnel, segments, calendar cohorts, weekly repeats, and experiment planning. Filters affect only compatible populations; no global date filter truncates outcome windows.

Screenshots: [segments](docs/img/dashboard_segments.png) · [cohorts](docs/img/dashboard_cohorts.png) · [experiment planning](docs/img/dashboard_experiment.png).

**Pipeline:** CSV → DuckDB staging and analytical marts → PostgreSQL reporting aggregates → Metabase. Python handles validation, user-clustered statistics, experiment planning, and static figures. PostgreSQL receives **14 tables / 515 aggregate rows**, not raw or user-level histories; Metabase uses a separate private application database.

**Stack:** Python 3.12, uv, DuckDB, NumPy/SciPy, matplotlib, Psycopg, PostgreSQL 17.12, Metabase v0.64.6. Python dependencies are locked; Docker images are pinned by version and digest. SQL lives in [`sql/`](sql/), parameters in [`config/analysis.toml`](config/analysis.toml), builders in [`src/`](src/), dashboard declarations in [`metabase/`](metabase/).

## Reproduce

Requirements: Python 3.12 managed through uv; Docker Desktop with a running Linux engine for BI. Commands below use PowerShell from the repository root. Screenshots and methodology can be reviewed without installing the services.

<details>
<summary>Environment, source data, analytical build, and local dashboard</summary>

### Environment and inputs

```powershell
uv sync --locked
New-Item -ItemType Directory -Force -Path data/raw
```

Download the dataset from Kaggle, sign in if required, and extract these five files directly into `data/raw/`:

```text
2019-Oct.csv
2019-Nov.csv
2019-Dec.csv
2020-Jan.csv
2020-Feb.csv
```

Audit all inputs, including read-only duplicate sensitivity:

```powershell
foreach ($month in @('2019-Oct', '2019-Nov', '2019-Dec', '2020-Jan', '2020-Feb')) {
    uv run --locked python src/audit_data.py --input "data/raw/$month.csv" --duplicates
    if ($LASTEXITCODE -ne 0) { throw "Audit failed: $month" }
}
```

### Build analysis

Run in order; stop and resolve any failed command before proceeding:

```powershell
uv run --locked python src/build_staging.py
uv run --locked python src/build_funnel.py
uv run --locked python src/build_analysis.py
uv run --locked python src/build_cohorts.py
uv run --locked python src/build_experiment.py
uv run --locked python src/plot_segments.py
uv run --locked python src/plot_cohorts.py
uv run --locked python src/plot_experiment.py
```

Outputs: `data/processed/shop.duckdb`, validated JSON reports in `data/reports/`, and figures in `docs/img/`. The default DuckDB limit is 1 GB and two threads. Rebuilding upstream invalidates dependent marts; rerun downstream stages in the order above. Business formulas are implemented once and reused by reporting.

### Start and populate BI

Start Docker Desktop, then:

```powershell
uv run --locked python src/local_services.py init
uv run --locked python src/local_services.py config
uv run --locked python src/local_services.py up
uv run --locked python src/export_to_postgres.py
uv run --locked python src/local_services.py status
```

`init` generates local credentials in ignored `.env` and retains existing settings. Keep that file with the database volume: database initialization runs only once. PostgreSQL is bound to `127.0.0.1:5433`; Metabase to [localhost:3000](http://localhost:3000). The helper locates Docker on PATH or in its standard Windows installation directory.

On first use, create an administrator account in the Metabase browser setup; the sample database can remain. Then authenticate locally and provision the project:

```powershell
uv run --locked python src/metabase_client.py login
uv run --locked python src/setup_metabase.py
uv run --locked python src/validate_metabase.py
```

Login prompts for email and a hidden password, saving only a session in ignored `metabase/local/`. The setup script prints the dashboard URL. Repeated runs update the same objects; the analytics connection uses a read-only role. Reporting snapshots must match the validated analytical outputs before provisioning.

Optional screenshot refresh uses Playwright with an installed Microsoft Edge browser:

```powershell
uv run --locked python src/capture_dashboard.py
```

Stop services while retaining data:

```powershell
uv run --locked python src/local_services.py stop
```

</details>

## Validation

The latest verified suite passed **95 tests**: 88 self-contained tests and seven opt-in PostgreSQL/Metabase integration tests. Checks cover event ordering, duplicate/price policies, boundary windows, overlapping users, repeat purchases, power calculations, repeat builds, and transactional rollback. Metabase results match PostgreSQL across **21 query/filter cases**; restoration into a separate empty application database was verified. Dashboard text was checked at 1366, 1600, and 1920 pixels.

Run the self-contained suite without source CSVs or services:

```powershell
uv run --locked python -m unittest discover -s tests
```

<details>
<summary>Include the seven live integration tests after starting services and logging in</summary>

```powershell
$env:RUN_LOCAL_POSTGRES_TESTS = '1'
$env:RUN_LOCAL_METABASE_TESTS = '1'
try {
    uv run --locked python -m unittest discover -s tests
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
} finally {
    Remove-Item Env:RUN_LOCAL_POSTGRES_TESTS -ErrorAction SilentlyContinue
    Remove-Item Env:RUN_LOCAL_METABASE_TESTS -ErrorAction SilentlyContinue
}
```

</details>

The analytical models and local dashboard are implemented. Final acceptance of the complete reproduction workflow remains pending.
