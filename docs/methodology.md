# Methodology

This document describes the working analysis design. The single-file input audit is implemented and tested on synthetic events; business-metric calculations are not implemented yet. Data-dependent choices, including duplicate handling and purchase-session validity, will be finalized after the source-data audit and before reporting results.

## Observation scope

Expected source coverage is October 2019–February 2020. Timestamps will be interpreted in UTC. Ingestion must verify file coverage, temporal gaps, event types, and identifier completeness before analysis.

October provides a lookback period. Subsequent first-purchase cohorts are still **first observed purchasers**, not confirmed new customers: earlier activity is unavailable.

## Data quality

- Preserve source files unchanged and record an input manifest.
- Profile exact duplicates by event type. Compare counts and purchase value with and without duplicates before choosing the primary policy; identical purchase rows may represent tracking duplication or multiple units. Exclude ingestion metadata from duplicate comparisons.
- Keep behavior events with nonpositive or missing prices flagged; exclude invalid values from monetary calculations and report their coverage. Do not assume they represent refunds.
- Keep missing brands and category codes as explicit unknown groups.
- Report events with missing user/session identifiers separately. Never merge unrelated missing-session events into one session.
- Reconcile exclusions, row counts, unique keys, and purchase-value totals at each transformation.

The initial audit treats empty and whitespace-only fields as missing. Nonempty values that cannot be parsed as a timestamp or finite numeric price are counted as invalid, separately from missing fields. Zero and negative prices are separate counts. All rows, including exact duplicate rows, remain included. Source timestamps are converted to UTC for bounds. Duplicate profiling and identifier-validity checks will be added before staging; the initial report does not certify the dataset as clean.

## Units and metrics

| Metric | Working definition | Interpretation |
|---|---|---|
| Session | `(user_id, user_session)` across all source files | Check duration, identifier reuse, and month-boundary continuity |
| Purchase session | Session containing a purchase event | An order proxy; multiple real orders within a session cannot be identified reliably |
| Purchase value | Sum of valid purchase-event prices under the selected duplicate policy | Observed event value; not profit or confirmed net sales |
| Session funnel | Existence of view → cart → purchase in chronological order within a session | Any product in the session; not a product-level cart reconstruction |
| Cart-to-purchase conversion | Sessions with a purchase after cart / sessions with cart | State explicitly whether entry from view is required |
| Session cart abandonment | Sessions with cart and no subsequent purchase in the same session / sessions with cart | Does not imply the customer never buys later |
| User funnel | Ordered steps within seven days of the first qualifying observed view | Require complete follow-up; allow steps across sessions |
| New observed visitor | First observed session of a user | Classify using past activity only |
| Repeat purchase within H days | Another purchase session after the first, within H days / eligible first-purchase users | H = 30 or 60; several item rows in the first session are not repeat purchases |

An ordered funnel must search for a valid event chain, rather than compare only the first timestamp of each event type. Equal timestamps do not reveal event order: the working rule allows equality and reports a sensitivity check using strict inequalities. Purchases outside a recorded funnel chain remain visible in coverage and reconciliation tables.

The exact revenue identity, on a consistent eligible population and period, is:

`observed users × purchaser share × purchase sessions per purchaser × mean purchase-session value`.

Conditional funnel conversions are diagnostic metrics. They need not explain every recorded purchase if preceding events are missing.

## Cohorts and complete follow-up

For each horizon H, require `first_purchase_time + H <= verified_observation_end` before constructing either the numerator or denominator. A verified end must reflect continuous source coverage, not simply the latest timestamp in a file.

Repeat purchase requires a distinct purchase-session proxy with a later timestamp. Repeated purchase rows within the first session do not qualify. Same-time purchases require a separate audit.

Calendar-month M1/M2 repurchase rates and cumulative 30/60-day repeat rates are different metrics and will be labeled separately. Incomplete cohort cells are NA, not zero. Direct 30-versus-60-day comparisons use a common population with 60 complete days.

## Black Friday comparison

The main first-observed-purchase cohort uses the half-open interval `[2019-11-25, 2019-12-02)` UTC. Baselines are `[2019-11-11, 2019-11-18)` and `[2019-11-18, 2019-11-25)`; `[2019-12-02, 2019-12-09)` is an additional comparison. A November 29-only cohort provides a sensitivity check.

These are calendar cohorts, not verified promotion exposures. All groups use the same lookback rules and complete follow-up horizons. Report cohort sizes, repeat-purchase rates, and observed purchase value per cohort member over the same window, stating whether the initial purchase is included.

Customer mix, seasonality, unknown discounts, and missing acquisition costs prevent a causal ROI claim. December trends can be described; displacement of December demand cannot be established from this comparison alone.

## Segments and statistical comparisons

Primary comparisons are new/returning observed visitors and price segments. Price bands will be defined from the first valid cart-event price in a pre-promotion reference period and then frozen. Do not define conversion segments using future purchase outcomes.

Report sample sizes, effect sizes in percentage points, uncertainty intervals, and practical magnitude. Repeated sessions from the same user are dependent: use a user-level summary or bootstrap entire users and recalculate the session metric within each resample. Brand groups may overlap and cannot be added as disjoint customer populations.

Distinguish prespecified comparisons from exploratory ones. Define a multiple-testing family and correction for exploratory comparisons. Statistical significance does not establish causality or business importance.

## Revenue scenarios and experiment design

For a single-purchase outcome, a scenario may use:

`eligible users × assumed absolute conversion lift × expected purchase value`.

For an outcome allowing multiple purchases, use `eligible users × assumed change in revenue per user`. Specify eligibility, horizon, value assumptions, and the difference between relative lift and percentage-point lift. Do not add overlapping segment opportunities. Confirm currency from the source before assigning a currency symbol.

The candidate experiment will use stable user-level assignment before treatment, 50/50 allocation, and one primary outcome. A working primary metric is purchase conversion within seven days of the first qualifying cart; revenue per eligible user over the same window is a secondary metric and includes zeros. Eligibility must change if the intervention occurs before cart.

Plan sample size from the baseline user conversion or empirical user-revenue variance, a business-relevant MDE, two-sided alpha 0.05, and power 0.80. Account for skew and repeated observations. Duration includes unique-user enrollment and a complete outcome window for the last enrolled user, aligned with weekly traffic patterns. Fix the stopping rule before the test.

Proposed guardrails include purchase value, checkout errors, cancellations/refunds, and checkout time. The latter three require additional instrumentation: `remove_from_cart` does not measure order cancellation. Historical cohort comparisons are not a completed A/B test.

## Decision record

When the audit changes a working definition, record the date, evidence, selected policy, affected tables/metrics, and sensitivity checks. Keep the main analysis reproducible from the same input files and configuration.
