# From Cart to Repeat Purchase

Product analytics of a cosmetics store: purchase funnel, cart abandonment, and repeat purchases around Black Friday 2019.

**Status: work in progress.** The research design is documented. Data processing and analysis have not been implemented; no findings are available yet.

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

[eCommerce Events History in Cosmetics Shop](https://www.kaggle.com/datasets/mkechinov/ecommerce-events-history-in-cosmetics-shop), published by Michael Kechinov / REES46 on Kaggle. Expected coverage: October 2019–February 2020; file coverage and dataset terms will be checked during ingestion.

Raw data is not included in this repository. The event schema has no order ID, confirmed item quantity, acquisition cost, or cost of goods. Purchase sessions will therefore be treated as order proxies, subject to validation. Abandoned-cart value is not equivalent to recoverable revenue, and observational cohort differences do not establish a causal promotion effect.

## Planned stack

Python 3.12 · uv · DuckDB / SQL · scipy / statsmodels · matplotlib · PostgreSQL · Metabase / Docker Compose.

DuckDB will process raw events; Python will handle statistical analysis and figure exports. PostgreSQL will serve prepared reporting tables to Metabase.

## Documentation

- [Methodology and metric definitions](docs/methodology.md)
- [Dashboard and chart design](docs/dashboard-design.md)
- [Implementation roadmap](docs/roadmap.md)

## Reproduction

The pipeline is not available yet. Tested setup and build commands will be added with the implementation. Downloaded data, credentials, and local database files will remain outside version control.
