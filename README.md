# From Cart to Repeat Purchase

Product analytics of a cosmetics store: purchase funnel, cart abandonment, and repeat purchases around Black Friday 2019.

**Status: work in progress.** The input audit has run on all five source files: 20,692,840 events. Daily coverage and exact-row duplicate sensitivity are measured. Staging, funnel/cohort calculations, and business recommendations are pending.

## Business question

Where does the observed purchase journey break down, which customer segments deserve investigation, and which product improvement should be tested first?

A second question examines whether customers whose first observed purchase occurred during Black Friday week make repeat purchases at different rates from nearby weekly cohorts over the same 30- and 60-day horizons.

## Planned analysis

- Validate event coverage, duplicates, prices, and session identifiers.
- Build an ordered view → cart → purchase funnel and compare cart abandonment across customer and price segments.
- Measure repeat purchases using complete follow-up windows.
- Estimate incremental revenue under explicit conversion scenarios and design an A/B test for one prioritized hypothesis.
- Present the results in a reproducible Metabase dashboard and a short decision memo.

## Data

[eCommerce Events History in Cosmetics Shop](https://www.kaggle.com/datasets/mkechinov/ecommerce-events-history-in-cosmetics-shop), published by Michael Kechinov / REES46 on Kaggle. The five source files cover October 2019–February 2020; actual timestamp coverage will be checked during ingestion. Dataset terms remain those specified by the publisher on Kaggle.

Raw data is not included in this repository. The event schema has no order ID, confirmed item quantity, acquisition cost, or cost of goods. Purchase sessions will therefore be treated as order proxies, subject to validation. Abandoned-cart value is not equivalent to recoverable revenue, and observational cohort differences do not establish a causal promotion effect.

## Input audit

Source-data audit completed on November 14, 2026, before any cleaning:

| File | Rows | Exact duplicate rows beyond the first copy |
|---|---:|---:|
| 2019-Oct.csv | 4,102,283 | 213,155 |
| 2019-Nov.csv | 4,635,837 | 246,693 |
| 2019-Dec.csv | 3,533,286 | 183,860 |
| 2020-Jan.csv | 4,264,752 | 225,100 |
| 2020-Feb.csv | 4,156,682 | 240,290 |
| **Total** | **20,692,840** | **1,109,098** |

Events are present on all 152 calendar days from October 1, 2019 to February 29, 2020. No timestamp/price parsing failures or unexpected event types were found. This does not establish complete tracking within each day.

The audit found 4,598 events without a session identifier, 104,157 zero-price events, and 131 negative-price events. `category_code` is missing in 98.29% of rows and `brand` in 42.32%; category IDs are present. Of the excess duplicate rows, 991,820 are `remove_from_cart`, while only 905 are `purchase`. Removing the latter would reduce the sum of positive purchase-event prices by 0.0561%.

The selected policy preserves source rows and will flag duplicate groups in staging. The alternate deduplicated purchase-value calculation is a sensitivity check, not the primary estimate. No cleaning or duplicate removal has been applied.

## Stack

Current: Python 3.12, uv, DuckDB 2.0.0. Dependency versions are recorded in `uv.lock`.

Planned: scipy/statsmodels for statistics, matplotlib for figures, PostgreSQL and Metabase/Docker Compose for reporting. These components have not been added yet.

## Documentation

- [Methodology and metric definitions](docs/methodology.md)

## Reproduction

Install uv and run the following commands from the repository root. Manual environment activation is not required.

```powershell
uv sync --locked
uv run --locked python -m unittest discover -s tests -v
```

Download the dataset from Kaggle using **Download** (sign in if required). Create the local input directory and extract the five CSV files directly into it:

```powershell
New-Item -ItemType Directory -Force -Path data/raw
```

```text
data/raw/
  2019-Oct.csv
  2019-Nov.csv
  2019-Dec.csv
  2020-Jan.csv
  2020-Feb.csv
```

The extracted files total approximately 2.43 GB according to Kaggle file metadata. Do not rename the files or place them inside an additional archive subfolder. Raw data, local reports, credentials, and database files are excluded from version control.

After extraction, run the single-file audit:

```powershell
uv run --locked python src/audit_data.py --input data/raw/2019-Oct.csv
```

The audit checks the header, counts every parsed row, reports event types, UTC timestamp bounds and daily coverage, missing fields, invalid timestamps/prices, zero and negative prices, and unexpected event types. It records the input SHA-256, file size, and runtime versions in `data/reports/2019-Oct_audit.json`. CSV structure errors stop the audit instead of silently skipping rows.

To reproduce the full five-file audit, including duplicate sensitivity:

```powershell
foreach ($month in @('2019-Oct', '2019-Nov', '2019-Dec', '2020-Jan', '2020-Feb')) {
    uv run --locked python src/audit_data.py --input "data/raw/$month.csv" --duplicates
    if ($LASTEXITCODE -ne 0) { throw "Audit failed: $month" }
}
```

All source columns are initially read as strings; parsing failures are counted separately. Exact duplicates match all nine original fields, excluding file metadata. `--duplicates` adds a read-only sensitivity calculation; it does not remove any rows. Larger groupings may use temporary disk space in `data/processed/audit_tmp/` under the 1 GB DuckDB memory limit. All five files were audited; detailed JSON reports remain local. This is the audit step, not the complete analytical pipeline.
