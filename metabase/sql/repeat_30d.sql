-- Black Friday week 30-day repeats. Grain/key: one fixed common-horizon cohort.
SELECT repeat_rate AS repeat_rate
FROM reporting.cohort_summary
WHERE cohort_id = 'black_friday_week' AND horizon_days = 30 AND population = 'common_horizon';
