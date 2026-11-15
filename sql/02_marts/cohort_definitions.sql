-- Define monthly entries and configured comparisons. Grain: one cohort. Key: cohort_id.
CREATE OR REPLACE TABLE cohort_definitions AS
WITH months AS (
    SELECT UNNEST(GENERATE_SERIES(DATE_TRUNC('month', analysis_start_utc),
        DATE_TRUNC('month', observation_end_exclusive_utc - INTERVAL '1 microsecond'),
        INTERVAL '1 month')) AS month_start
    FROM cohort_parameters
)
SELECT 'month_' || STRFTIME(month_start, '%Y_%m') AS cohort_id,
    STRFTIME(month_start, '%Y-%m') AS cohort_label, 'calendar_month' AS family,
    GREATEST(month_start, p.analysis_start_utc) AS entry_start_utc,
    LEAST(month_start + INTERVAL '1 month', p.observation_end_exclusive_utc) AS entry_end_exclusive_utc
FROM months CROSS JOIN cohort_parameters p
UNION ALL
SELECT cohort_id, cohort_label, family, entry_start_utc, entry_end_exclusive_utc
FROM configured_purchase_cohorts;
