# Methodology

This document describes the working analysis design. All five files are loaded into validated staging, with duplicate flags and source-session diagnostics. The duplicate-retention and 30-minute episode policies are selected. The episode table and business-metric calculations are not implemented yet.

## Observation scope

The input audit found 20,692,840 events across five files, with events on every calendar day from October 1, 2019 to February 29, 2020. Timestamps are interpreted in UTC. File timestamp ranges are within their named months and do not overlap; the per-file duplicate counts therefore cover exact duplicates across this dataset. No entire day is absent, but that alone does not prove complete tracking within days.

October provides a lookback period. Subsequent first-purchase cohorts are still **first observed purchasers**, not confirmed new customers: earlier activity is unavailable.

## Data quality

- Preserve source files unchanged and record an input manifest.
- Profile exact duplicates by event type. Compare counts and purchase value with and without duplicates before choosing the primary policy; identical purchase rows may represent tracking duplication or multiple units. Exclude ingestion metadata from duplicate comparisons.
- Keep behavior events with nonpositive or missing prices flagged; exclude invalid values from monetary calculations and report their coverage. Do not assume they represent refunds.
- Keep missing brands and category codes as explicit unknown groups.
- Report events with missing user/session identifiers separately. Never merge unrelated missing-session events into one session.
- Reconcile exclusions, row counts, unique keys, and purchase-value totals at each transformation.

The input audit treats empty and whitespace-only fields as missing. Nonempty values that cannot be parsed as a timestamp or finite numeric price are counted as invalid, separately from missing fields. Zero and negative prices are separate counts. All rows, including exact duplicate rows, remain included. Source timestamps are converted to UTC for bounds. Daily and event-type totals reconcile with each file's row count. Identifier-validity and session-integrity checks are still required; this report does not certify the dataset as clean.

### Audit evidence and duplicate decision — November 14, 2026

- 1,109,098 rows (5.3598% of input) are extra copies beyond the first matching row; 991,820 belong to `remove_from_cart`, 115,342 to `cart`, 1,031 to `view`, and 905 to `purchase`.
- A duplicate matches all nine original fields as parsed strings; empty fields are parsed as NULL. Input filename and row position are not part of this comparison.
- The 905 excess purchase copies represent 0.0703% of purchase rows. The sum of positive purchase-event prices is 6,351,830.29 before exact deduplication and 6,348,267.70 after it: a difference of 3,562.59, or 0.0561%. These are recorded event-price sums in source units, not confirmed net sales or order totals.
- The sensitivity query uses `DECIMAL(24, 6)` for price arithmetic; no price-precision mismatches were found in the source files.
- **Selected policy:** preserve all rows. Staging contains a duplicate-group size and membership flag; these flag every member of a matching group. The excess-row count remains `group size - 1`. Do not infer that matching purchase rows are tracking errors, because item quantity is unknown. Report the alternate deduplicated monetary estimate as sensitivity.
- An ordered session funnel counts step existence, so exact repeated copies of the same event do not change whether a qualifying chain exists. Event-volume analyses remain sensitive to duplication and require explicit labeling.
- No source rows were removed or flagged in-place. Staging flags are implemented separately in DuckDB.

There are 4,598 events without a session identifier; none are purchase events. There are 104,157 zero-price events (one purchase) and 131 negative-price events (126 purchases). `category_code` is missing in 98.29% of rows, while `category_id` is populated; `brand` is missing in 42.32%. No user ID, product ID, category ID, event-time, event-type, or price values are missing, and no timestamp/price parse errors or unexpected event types were found. Nonpositive prices have a staging flag. These values must not be silently treated as refunds.

### Staging rules

`raw_events` preserves the nine original string fields and adds a filename and record number within that file. The record number supports traceability; it is not evidence of behavioral order for tied timestamps. Duplicate grouping precedes type conversion and excludes those two metadata fields.

`stg_events` stores finite UTC timestamps, integer IDs, and `DECIMAL(24, 6)` prices. IDs must contain only digits after trimming and fit in signed BIGINT; zero is not rejected without a source-specific rule. Unrepresentable values become NULL with a quality flag. Price conversion is checked for numeric precision loss. Blank session tokens become NULL; nonblank tokens are trimmed without changing case. No UUID format restriction is imposed.

Session eligibility requires a convertible user ID, a nonblank session token, and a valid finite timestamp. Product/category/price problems remain flagged without removing behavior events. All 20,692,840 rows remain in staging; 20,688,242 are session-eligible. No ID or price conversion failures occurred in the real dataset. The positive purchase-event price sum reconciles between raw data, staging, and eligible session aggregates: 6,351,830.29 source units, with zero value excluded by session eligibility.

### Source-session diagnostics and episode decision — November 14, 2026

The preliminary `sessions` table uses `(user_id, user_session)` across every file, yielding 4,536,272 groups and 155,617 purchase-containing groups. It is a diagnostic grouping, not the final visit definition.

- 272 session tokens belong to multiple users, affecting 603 composite-key groups. The user ID must remain part of the key.
- 14,228 groups cross month boundaries and must not be truncated during monthly ingestion.
- 36,194 groups span more than 24 hours and 14,717 span more than seven days. The maximum span is 13,099,556 seconds.
- 2,686 purchase groups contain multiple distinct purchase timestamps; 1,262 have consecutive purchase timestamps more than 30 minutes apart, including 676 with gaps over 24 hours.
- 184,451 groups contain consecutive distinct activity timestamps more than 30 minutes apart, generating 274,307 additional fragments under that threshold.

**Selected policy for the funnel:** within each composite source key, start a new episode when the activity gap is strictly greater than 30 minutes. Equal timestamps and gaps of exactly 30 minutes stay in the same episode; a month boundary alone does not start a new one. Never merge separate source tokens or different users. The implied total is 4,810,579 episodes (+6.05%). Keep the original source-key version as sensitivity. This threshold is an explicit operational assumption and does not establish the true number of visits or orders. Episode materialization is the next step; the current table still contains the original source-key groups.

## Units and metrics

| Metric | Working definition | Interpretation |
|---|---|---|
| Session episode | `(user_id, user_session, episode_number)`, split at inactivity gaps >30 minutes across all source files | Selected rule; episode table pending. Original source-key groups remain a sensitivity baseline |
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
