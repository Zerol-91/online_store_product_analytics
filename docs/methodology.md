# Methodology

This document describes the analysis definitions and selected prospective experiment. Validated staging, 30-minute episodes, ordered session/user funnels, segment comparisons, repeat-purchase cohorts, conditional value scenarios, and experiment planning are implemented. PostgreSQL/Metabase reporting remains pending; no experiment has been run.

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

The input audit treats empty and whitespace-only fields as missing. Nonempty values that cannot be parsed as a timestamp or finite numeric price are counted as invalid, separately from missing fields. Zero and negative prices are separate counts. All rows, including exact duplicate rows, remain included. Source timestamps are converted to UTC for bounds. Daily and event-type totals reconcile with each file's row count. Identifier conversion and session-integrity checks have been run; known limitations remain explicit below.

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

**Selected policy for the funnel:** within each composite source key, start a new episode when the activity gap is strictly greater than 30 minutes. Equal timestamps and gaps of exactly 30 minutes stay in the same episode; a month boundary alone does not start a new one. Never merge separate source tokens or different users. The materialized total is 4,810,579 episodes (+6.05%). Keep the original source-key version as sensitivity. This threshold is an explicit operational assumption and does not establish the true number of visits or orders. `episodes` is the primary episode view; `sessions` retains the original source-key diagnostic groups.

## Units and metrics

| Metric | Working definition | Interpretation |
|---|---|---|
| Session episode | `(user_id, user_session, episode_number)`, split at inactivity gaps >30 minutes across all source files | Implemented; original source-key groups remain a sensitivity baseline |
| Purchase session | Session containing a purchase event | An order proxy; multiple real orders within a session cannot be identified reliably |
| Purchase value | Sum of valid purchase-event prices under the selected duplicate policy | Observed event value; not profit or confirmed net sales |
| Session funnel | Existence of view → cart → purchase in chronological order within a session | Any product in the session; not a product-level cart reconstruction |
| Cart-to-purchase conversion | Sessions with a purchase after cart / sessions with cart | State explicitly whether entry from view is required |
| Session cart abandonment | Sessions with cart and no subsequent purchase in the same session / sessions with cart | Does not imply the customer never buys later |
| User funnel | Ordered steps within seven days of the first qualifying observed view | Require complete follow-up; allow steps across sessions |
| New observed visitor | First observed session of a user | Classify using past activity only |
| Repeat purchase within H days | Another purchase session after the first, within H days / eligible first-purchase users | H = 30 or 60; several item rows in the first session are not repeat purchases |

An ordered funnel must search for a valid event chain, rather than compare only the first timestamp of each event type. Equal timestamps do not reveal event order: the working rule allows equality and reports a sensitivity check using strict inequalities. Purchases outside a recorded funnel chain remain visible in coverage and reconciliation tables.

### Implemented session funnel — November 15, 2026

Parameters are recorded in `config/analysis.toml`. Both episode and original source-key units use the same SQL chain calculation. For each unit, find the earliest view, then the earliest cart at/after that view, then the earliest purchase at/after that qualifying cart. An earlier cart or purchase does not prevent a later valid chain from qualifying. This is an any-product visit funnel, not product-level cart reconstruction. Duplicate copies affect event counts but not sequence existence.

The full-chain cart denominator is the number of units with a cart after a view. Separately, the any-cart denominator includes every unit containing a cart, and conversion requires a purchase at/after its earliest cart, regardless of view. A unit that purchased before adding to cart can be a purchasing unit while still having no cart→purchase pair. Nonpositive or invalid prices do not remove a recorded purchase event from these behavioral rates; monetary sums only include valid positive prices.

Primary counts: 4,501,112 viewed episodes → 745,696 qualifying cart episodes → 95,850 full-chain episodes. View→cart conversion is 16.5669%, and cart→purchase conditional on the full funnel is 12.8538%. Across all 1,049,303 cart episodes, 122,189 have a cart→purchase pair (11.6448%) and 927,114 do not (88.3552%). These are distinct denominators.

There are 157,595 purchase-containing episodes. The 61,745 without a complete ordered chain decompose into 34,576 with no cart, 830 whose purchases precede their first cart, and 26,339 with a valid cart→purchase pair but no full view→cart→purchase chain. This describes recorded sequences; it does not identify tracking errors or user motives. The full-chain count is not a denominator for all observed purchase value.

Strict `<` ordering gives 744,550 qualifying carts and 95,808 full chains, versus 745,696 and 95,850 under the primary `<=` rule. Original source-key units give 985,813 cart units and 125,459 cart→purchase pairs (12.7265%), versus 11.6448% using episodes: a 1.0817 percentage-point difference caused by the analysis definition. This is not a product uplift.

The observation interval is `[2019-10-01 00:00:00, 2020-03-01 00:00:00)` UTC. Rates currently include all observed eligible units. Flag units whose first event is within 30 minutes of the start, and units whose last event plus 30 minutes reaches or exceeds the end. The primary episode counts are 126 near-start units and 176 potentially open units at the end; the latter include 49 classified as abandoned-cart episodes. These flags identify boundary exposure, not proven missing activity. Later analysis must not treat within-episode abandonment as permanent customer loss.

The mapping keeps all 20,688,242 session-eligible events with unique source-record keys; 4,598 ineligible events stay in staging. No purchase event or positive purchase value is excluded by session eligibility in this dataset. Each session definition independently reconciles to 6,351,830.29 in positive purchase-event prices. Do not add those repeated sensitivity totals together.

Builds validate mapping uniqueness, episode transitions, per-definition event/value totals, unit keys, sequence timestamps, monotone funnel counts, and purchase coverage. Both builders replace derived tables transactionally. A successful staging rebuild invalidates episode and funnel outputs; rebuild them before analysis. Source checksums, staging/table fingerprints, settings, and runtime versions are recorded in local reports. Repeatability and rollback are tested with synthetic event histories.

The exact revenue identity, on a consistent eligible population and period, is:

`observed users × purchaser share × purchase sessions per purchaser × mean purchase-session value`.

Conditional funnel conversions are diagnostic metrics. They need not explain every recorded purchase if preceding events are missing.

### Implemented seven-day user window — November 15, 2026

Build the first observed activity, view, and purchase timestamps using every event with valid user ID and timestamp, including events without a session token. Keep the complete history when establishing the first view; a later date filter must not re-anchor an existing user at a later view.

The outcome window is `[first_view, first_view + 7 days]`, including the deadline. Because observation ends at an exclusive timestamp, eligibility requires `first_view + 7 days < observation_end_exclusive`. A user whose deadline equals the exclusive end is not fully observed. Users without a view or without full follow-up remain in the user table with flags and are excluded from the funnel denominator.

The user window reuses the same ordered-chain SQL as session funnels; only the input population/window changes. Events can belong to different or missing sessions. A purchase after the deadline cannot complete the funnel, and an earlier purchase does not prevent a later valid chain. Primary `<=` and strict `<` timestamp rules are retained.

Across the full observed first-view history, 1,529,295 users have complete windows. Of these, 283,387 have a qualifying cart and 68,921 complete the chain: 18.5306% view→cart, 24.3205% cart→purchase, and 4.5067% view→purchase. There are 70,880 users with any purchase inside the window; 1,959 lack a complete ordered chain. Excluded from the view-entry denominator are 41,604 users without a view and 68,459 with incomplete windows.

The user table covers 1,639,358 observed users. Among complete-window first-view users, 89,391 have an earlier recorded activity and 2,850 have an earlier purchase. This is a first-observed-view journey, not a confirmed first-ever purchase journey. It is also not the seven-day post-cart baseline required for the proposed experiment.

The primary entry cohort starts on November 1, 2019, after the October reference period: 1,140,964 mature first-view users, 169,884 qualifying carts, and 49,385 full chains. The step rates are 14.8895% and 29.0698%; overall view-to-purchase is 4.3284%. Another 388,331 first-view users entered before November and do not re-enter at a later view. The all-mature population above remains a separate sensitivity summary. This entry restriction applies to the user funnel and cart-segment analysis; the full-history episode diagnostics retain October.

## Cohorts and complete follow-up

The first-purchase anchor uses all available October–February purchase history. Primary cohorts start in November; an October purchaser who buys in November does not enter a November first-purchase cohort. These are first **observed** purchasers, not confirmed first-ever customers.

### Purchase-proxy audit and selected policy — November 15, 2026

There are 1,287,007 purchase-event rows in 157,595 purchasing episodes, covering 110,518 observed purchasers. Their positive event-price sum reconciles to 6,351,830.29 source units. No purchase event lacks session eligibility in this dataset; the cohort build stops if a future source contains uncovered purchases, rather than silently shifting the first-purchase anchor.

There are 1,683 episodes with multiple purchase timestamps; the largest first-to-last purchase span is 8,080 seconds. Several item rows, exact repeated rows, or later purchase timestamps **within the same episode do not count as repeat orders**. Across different episodes there are five simultaneous-start groups (11 episodes), including one user with two initial episodes. Nine episodes overlap or tie earlier purchase spans, affecting eight users. There are also 793 successive episode-start pairs separated by at most 30 minutes. Without order IDs, separate tokens may still represent one real checkout.

**Accepted policy:** keep the selected episode definition without merging across tokens. Anchor each buyer at the earliest purchase timestamp. A repeat requires another purchasing episode whose **first purchase timestamp is strictly later** than that anchor. Episodes starting simultaneously with the initial purchase are not repeats; no arbitrary token chooses which is the first order. A distinct episode can count as a repeat while an earlier episode is still active; the sensitivity population excludes all eight users with overlapping/tied purchase spans. This is a purchase-episode proxy, not a validated count of orders.

### Elapsed-day outcomes and complete follow-up

For horizon H, use the inclusive window `[first_purchase, first_purchase + H days]`. Because observation ends at an exclusive timestamp, eligibility requires `first_purchase + H days < observation_end_exclusive`. A deadline equal to March 1, 2020 00:00 UTC is incomplete. The verified boundary comes from the source-coverage audit, not simply the latest event timestamp. Repeated flags and value outcomes remain NULL for incomplete windows.

`buyer_outcomes` retains one row per buyer/horizon. `horizon_mature` uses everyone mature at that horizon and is a diagnostic population; late entry cohorts may be only partially mature. **Primary 30/60-day comparisons and cumulative curves use `common_horizon`: the same users with complete 60-day follow-up for both horizons.** `common_horizon_no_overlap` adds the eight-user ambiguity exclusion. Each summary reports the full cohort size and eligible denominator separately. A zero eligible denominator produces no rate, rather than zero conversion.

The cumulative curve at day d counts users with their first qualifying repeat no later than `first_purchase + d days`, divided by the fixed 60-day-mature population. Repeat at the deadline is included, and day zero is zero by the strict repeat rule.

Observed value is the sum of **positive purchase-event prices**, preserving the agreed duplicate policy. Total value per eligible user includes the initial purchase; repeat value per eligible user includes only episodes beginning strictly after the first-purchase anchor and includes zero for non-repeaters. Both sums use actual event timestamps inside the outcome window. An episode crossing a deadline does not contribute its entire value early. Simultaneous initial episodes contribute to total value, not repeat value. Report means and medians; these are source price units, not confirmed revenue, profit, or ROI.

### Calendar M1/M2

Calendar-month repurchase is a separate metric. For a first-purchase month C, M1 and M2 count distinct cohort users with a qualifying repeat episode starting in calendar month C+1 or C+2; the denominator is the full cohort size. This is not a cumulative 30/60-day measure. A target month is complete when its exclusive end is at or before the observation boundary. Incomplete cells are NA. For example, January M1 (February) is complete, while January M2 (March) is not.

### Descriptive uncertainty

Each cohort/horizon has one binary outcome per eligible user. Descriptive normal 95% intervals reuse the user-clustered ratio implementation with one observation per user. Counts uniquely determine these marginal intervals; zero-variance and empty cases retain their explicit inference status. The curve shows endpoint intervals only, not a simultaneous confidence band. These observational cohort comparisons are descriptive: no new hypothesis tests or causal effect estimates are introduced, and they do not extend the earlier two-contrast segment-testing family. Calendar shocks and changing customer mix remain limitations.

## Black Friday comparison

The main first-observed-purchase cohort uses the half-open interval `[2019-11-25, 2019-12-02)` UTC. Baselines are `[2019-11-11, 2019-11-18)` and `[2019-11-18, 2019-11-25)`; `[2019-12-02, 2019-12-09)` is an additional comparison. A November 29-only cohort provides a sensitivity check.

These are calendar cohorts, not verified promotion exposures. All groups use the same lookback rules and complete follow-up horizons. Report cohort sizes, repeat-purchase rates, and observed purchase value per cohort member over the same window, stating whether the initial purchase is included.

The November 29-only sensitivity overlaps the Black Friday week and must not be added to it. Main weekly cohorts are disjoint and use the common 60-day-mature population for both 30- and 60-day results. The configured windows, horizons, and calendar ages are recorded in `config/analysis.toml`.

Monthly and weekly memberships also overlap. Do not sum summary rows across cohort families, horizons, or maturity populations as distinct users or purchase value.

Customer mix, seasonality, unknown discounts, and missing acquisition costs prevent a causal ROI claim. December trends can be described; displacement of December demand cannot be established from this comparison alone.

## Segments and statistical comparisons

The following definitions were accepted on November 15, 2026. The segment unit is a cart episode starting in `[2019-11-01, 2020-03-01)` UTC. Its outcome is at least one purchase at/after the first cart within that episode, under the configured timestamp rule. This is neither a seven-day post-cart outcome nor item-level conversion: the purchase need not contain the item used to classify entry price. Potentially open episodes remain included and their counts are reported.

**Visitor status.** An episode is `first_observed` when its start equals the user's first recorded activity across the full source history; otherwise it is `returning`. Sessionless events contribute to that history. Simultaneous first episodes both receive the first-observed label. A user can contribute to both groups on different visits. October provides lookback, not proof that a visitor had never used the store before.

**Entry price.** Use only cart events at the episode's very first cart timestamp. For each unique product at that timestamp, take the median of distinct positive prices, then the median across products. Exact repeated rows therefore do not weight the price. If there is no positive price at that timestamp, assign `Unknown`; do not substitute a later cart or purchase price. This is an entry-item price indicator, not basket value or order value.

**Frozen price bands.** Continuous terciles use October first-cart entry prices only (`[2019-10-01, 2019-11-01)`); no conversion outcomes enter calibration. The 241,594 priced reference episodes give cutpoints **3.00** and **6.03** in source price units. Low is `price <= 3.00`, middle is `3.00 < price <= 6.03`, high is `price > 6.03`; Unknown is separate. Tied prices can produce unequal group sizes. Quantiles are rounded to six decimal places to avoid decimal interpolation truncation at an exact boundary. Expected cutpoints are fixed in configuration; a changed calibration fails the build for review.

**Estimand and clustering.** For segment g, let `Y_ug` count converted episodes and `N_ug` count cart episodes for user u. The estimate is `p_g = SUM(Y_ug) / SUM(N_ug)`, an episode conversion ratio, rather than a mean of individual user rates. Its user influence is `a_ug = (Y_ug - p_g*N_ug) / SUM(N_ug)`. The estimated variance is `G/(G-1) * SUM(a_ug^2)` over G users present in the segment. The delta-method approach follows [Deng, Knoblich and Lu (2018)](https://arxiv.org/abs/1803.06336).

Report two-sided normal 95% intervals for descriptive segment rates. The two prespecified contrasts are **returning minus first_observed** and **high minus low price**, expressed in percentage points. For each difference, align users across both groups (zero counts when absent), use influence `a_uB - a_uA`, and apply the same variance correction over their union. This retains covariance for users in both groups. With family alpha 0.05 and two comparisons, Bonferroni gives a **97.5% interval for each contrast** and adjusted p-value `MIN(1, 2*p)`. The pair of contrast intervals has at least 95% simultaneous asymptotic coverage; the descriptive rate intervals are not simultaneous. Middle and Unknown are descriptive only.

The approximation assumes independent user clusters and sufficiently many non-dominant clusters. Report the largest user's episode share as a diagnostic. Empty groups, fewer than two clusters, or degenerate variance do not receive a misleading zero-width interval. Normal intervals are not clipped to [0,1]. Shared calendar shocks, changing customer mix, and unmeasured price/product differences are not controlled by clustering. These are observational associations, not treatment effects or proof that price or visitor status causes conversion. Users across price groups may overlap; group user counts cannot be added as distinct people.

## Revenue scenarios and experiment design

For a single-purchase outcome, a scenario may use:

`eligible users × assumed absolute conversion lift × expected purchase value`.

For an outcome allowing multiple purchases, use `eligible users × assumed change in revenue per user`. Specify eligibility, horizon, value assumptions, and the difference between relative lift and percentage-point lift. Do not add overlapping segment opportunities. Confirm currency from the source before assigning a currency symbol.

### Selected hypothesis and enrollment — November 15, 2026

The selected prospective intervention shows the complete cost and available fulfillment conditions in the cart before checkout, without adding a discount. The hypothesized mechanism is reduced uncertainty. The source does not contain the current interface, shipping charges, cost visibility, or users' reasons for leaving; this is a test candidate, not an explanation established by the funnel.

The selected audience is **all observed cart users in the analysis entry period**, including users with October carts or prior purchases. Enroll each user once, at their earliest valid cart timestamp in `[2019-11-01, 2020-03-01)` UTC. Keep the earliest cart across the full source as history, but do not require it to occur after November. This is a new experimental eligibility definition; it does not re-anchor the existing first-view or first-purchase cohorts.

Use valid user IDs and timestamps even when session tokens are missing. The outcome window is inclusive `[entry, entry + 7 days]`, with full follow-up only when the deadline is strictly before the exclusive observation end. Primary conversion is any purchase at/after entry within that window, across sessions and products. Strictly later timestamps provide sensitivity. Preserve duplicates and nonpositive-price purchase events for behavioral outcomes; sum only positive purchase prices for value.

The baseline has 292,094 period-cart users, including 277,852 with complete windows and 14,242 with incomplete follow-up. Among mature users, 27,290 have an earlier October cart. Primary conversions are 72,498 / 277,852 = **26.0923%**, with descriptive 95% interval **[25.9290%, 26.2556%]**. Strict ordering gives 72,496 conversions. These rates have a different entry, population, and horizon from the episode and first-view funnels.

Seven-day positive purchase-event value totals 2,875,084.26 source units. Its per-user mean is 10.3475, median 0, sample standard deviation 29.8075, p95 54.8845, p99 124.9698, and maximum 1,850.40. The conditional mean among converted users is 39.6574. It includes every positive purchase event in the user's outcome window, possibly spanning several purchasing episodes; it is not average order value.

The prospective experiment uses stable user-level assignment before any variant exposure, 50/50 allocation, and one primary outcome: purchase conversion within seven days. Analyze all eligible assigned users (intention to treat), not only those who later open the cart or see the block. `cart` records adding an item, not proof of viewing the cart page. A real implementation therefore needs eligibility, assignment, cart-page and block-exposure events; the historical baseline is an eligibility proxy, not an observed experiment. Seven-day value per eligible user, including zeros, is secondary. If the intervention moves before cart, revise eligibility and the outcome anchor before planning.

Plan sample size from the baseline user conversion or empirical user-revenue variance, a business-relevant MDE, two-sided alpha 0.05, and power 0.80. Account for skew and repeated observations. Duration includes unique-user enrollment and a complete outcome window for the last enrolled user, aligned with weekly traffic patterns. Fix the stopping rule before the test.

The sample-size calculation uses the normal approximation for two independent proportions: pooled variance under the null and separate variances under the alternative, as described in the [statsmodels power documentation](https://www.statsmodels.org/stable/generated/statsmodels.stats.proportion.power_proportions_2indep.html). The implementation uses SciPy and solves both tails numerically; no additional statistics package is required. On November 15, 2026 the author selected +1 percentage point as the primary planning MDE, retaining +0.5/+2 pp as sensitivity. The separate monetary scenario assumes unchanged seven-day positive purchase-event value per converted user; that assumption was also accepted on November 15, 2026. The validated report and figure are built by `build_experiment.py` and `plot_experiment.py`.

### Choosing a detectable effect

Distinguish the economically worthwhile effect from the statistical MDE: at a fixed sample size, MDE is the true effect at which the test reaches the selected power. [J-PAL](https://www.povertyactionlab.org/resource/power-calculations) describes planning either sample size from MDE or detectable effect from available sample size. Resource constraints are a possible justification when stated explicitly, as discussed by [Lakens](https://lakens.github.io/statistical_inferences/08-samplesizejustification). They do not establish economic profitability.

An illustrative adaptation of [contribution-margin break-even analysis](https://openstax.org/books/principles-managerial-accounting/pages/3-2-calculate-a-break-even-point-in-units-and-dollars) is `delta_CR_break_even = (F / U + c) / m`: U is the eligible rollout population over a defined horizon, F the relevant incremental fixed costs, c additional per-eligible-user costs, and m the contribution from an additional converted user over the same seven-day outcome window, after purchase-related variable costs. This assumes unchanged contribution per converted user and no other effects on existing purchasers. Rollout population is not the test sample size. The required margin, costs, and rollout inputs are unavailable here; 39.6574 in positive event prices cannot substitute for m. No economic MDE is claimed.

The selected educational study budget is four weeks, leaving 21 enrollment days and seven follow-up days. Historical enrollment from November 1 supplies 65,102 users over those 21 days; 32,551 per arm implies approximately 0.9701 percentage-point detectable uplift at alpha 0.05 and power 0.80. This supports the selected +1 pp as a resource-based design. It is not a future traffic forecast or proof of a business threshold.

MDE is not the smallest observed estimate that can become significant; smaller effects can be detected with lower power ([MDRC](https://www.mdrc.org/work/publications/why-estimates-below-minimum-detectable-effect-can-be-statistically-significant)). Our sample-size calculation concerns a test against zero difference, not a test that the effect exceeds a positive profitability threshold. Such a business claim would require the economic inputs and an appropriately planned analysis.

Proposed guardrails include purchase value, checkout errors, cancellations/refunds, and checkout time. The latter three require additional instrumentation: `remove_from_cart` does not measure order cancellation. Historical cohort comparisons are not a completed A/B test.

### Prospective protocol and conditional value scenarios

**Assignment and estimand.** Randomize eligible users 50/50 before their first possible exposure to the variant and keep assignment stable across sessions. The control keeps the current flow; the treatment adds the cost/fulfillment information. Analyze one record per eligible assigned user, regardless of whether the information block is subsequently viewed. Primary outcome is any purchase within seven days of inclusion. The main estimand is treatment minus control conversion in percentage points; report relative lift separately. Verify the actual control experience and tracking contract before a real launch.

**Sample and timing.** At historical baseline 26.0923% and alternative 27.0923%, the normal two-sided design requires 30,643 users per arm (61,286 total) to reach at least 80% power at alpha 0.05. The next smaller integer sample falls below target power. Historical replay beginning November 1 reaches the required total on day 20; rounding enrollment to complete weeks gives 21 days, followed by seven days for all outcomes. Enroll for at least two complete weeks in the sensitivity plans. The +0.5/+2 pp scenarios require 121,833/7,751 users per arm and 105/21 total days in the same replay. The smaller MDE exceeds the selected four-week budget.

**Stopping and analysis.** For the selected design, preregister 21 enrollment days and a single analysis after seven more days. The minimum target is 30,643 users in each arm. Validate the expected eligible traffic before launch. Do not stop early because an interim p-value looks significant, or extend after seeing the effect. If actual enrollment falls short, report the resulting lower sensitivity and interval rather than treating a nonsignificant result as evidence of no useful effect. A longer design should be agreed before launch, without inspecting treatment outcomes. At readout check assignment balance and tracking, then report the two-sided primary comparison and 95% effect interval. Demonstrating a positive effect and demonstrating profitability are different claims.

**Secondary outcome and proposed guardrails.** Report positive purchase-event value per eligible user with zeros, its distribution, and uncertainty based on users; do not compare only purchasers. Checkout error rate, processing latency, cancellations, and refunds require new events and operational tolerance thresholds agreed before a live launch. Those inputs are absent from the historical source, so the portfolio protocol does not claim an instrumented, launch-ready production test. Do not use `remove_from_cart` as a cancellation/refund guardrail.

**Conditional value.** For the accepted scenario let V be mean positive purchase-event value among converted users within their seven-day window (39.6574286187 source units), N=10,000 eligible users, and delta an assumed conversion uplift. Assuming V is unchanged, the added positive event-price sum is `N * delta * V`; equivalently the change in mean value per eligible user is `delta * V`. This identity allows several purchasing episodes in the window and does not require an order count. It produces 1,982.87 / 3,965.74 / 7,931.49 units for +0.5/+1/+2 pp. A zero-uplift reference gives zero additional value. The table labels these as conditional scenarios: the intervention can change purchase mix or V, and there is no observed treatment effect, verified currency, margin, cost estimate, or ROI.

The build stores four scenario rows, including the zero reference, in `experiment_scenarios`. Empty or boundary conversion baselines retain an explicit unavailable planning status instead of invented sample sizes. Baseline and scenario tables are committed in the same database transaction; a late planning validation failure restores the previous results.

## Decision record

When the audit changes a working definition, record the date, evidence, selected policy, affected tables/metrics, and sensitivity checks. Keep the main analysis reproducible from the same input files and configuration.
