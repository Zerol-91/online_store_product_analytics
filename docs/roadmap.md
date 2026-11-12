# Implementation roadmap

Current status: research design documented; implementation and analysis are pending.

| Milestone | Deliverable | Completion check |
|---|---|---|
| 0. Research design | Scope, metric definitions, data audit plan | Units, windows, assumptions, and limits are explicit |
| 1. Reproducible setup | Locked Python environment and a small end-to-end ingestion/build run | One documented command produces a validated table and figure |
| 2. Data foundation | Full event audit, staging, session/purchase/user tables | Reconciled counts and values, tested keys, month-boundary handling |
| 3. Funnel analysis | Ordered funnel and primary segment comparisons | Explicit denominators, effect sizes, and uncertainty |
| 4. Cohort analysis | Mature repurchase cohorts and Black Friday comparison | Equal horizons, no immature observations counted as zero |
| 5. Product decision | Revenue scenarios and a proposed experiment | Assumptions, MDE, sample size, duration, and guardrails documented |
| 6. Dashboard | Prepared PostgreSQL tables and restorable Metabase content | BI matches the analysis; repeated setup does not duplicate content |
| 7. Final report | Findings, exported figures, and tested reproduction guide | All reported values trace back to the same data pipeline |

Each milestone ends with validation and a review of the next step. Data-quality findings may change definitions or scope; such changes are recorded in the methodology before downstream results are updated.

## Scope priorities

The first version focuses on two segment comparisons, 30/60-day repurchasing, one product recommendation, and one dashboard page. Detailed brand analysis and time-to-first-purchase breakdowns are optional. Forecasting LTV, modeling churn, and proving promotion ROI are outside scope.

## Progress

- [x] Document the initial scope and working analysis design.
- [ ] Validate source access, coverage, and data-dependent definitions.
- [ ] Build and validate the pipeline.
- [ ] Complete funnel and cohort analysis.
- [ ] Design the experiment and revenue scenarios.
- [ ] Build the dashboard and publish the final report.
