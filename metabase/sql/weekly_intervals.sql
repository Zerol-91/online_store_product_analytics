-- Same 60-day-mature base at both horizons. Grain/key: cohort/horizon.
SELECT s.cohort_label AS cohort, s.horizon_days AS day, s.eligible_users AS users,
    s.repeat_users, s.repeat_rate, i.ci_low, i.ci_high
FROM reporting.cohort_summary s
JOIN reporting.cohort_rate_intervals i
    USING (cohort_id, horizon_days, population)
WHERE s.family = 'calendar_week' AND s.population = 'common_horizon'
ORDER BY s.entry_start_utc, s.horizon_days;
