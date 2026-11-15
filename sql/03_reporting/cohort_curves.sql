-- Track cumulative repeat purchase on one mature population. Grain: cohort/day. Key: (cohort_id, day).
CREATE OR REPLACE TABLE cohort_curves AS
WITH days AS (
    SELECT UNNEST(GENERATE_SERIES(0, comparison_horizon_days)) AS day FROM cohort_parameters
)
SELECT d.cohort_id, d.cohort_label, day.day,
    COUNT(b.user_id) AS eligible_users,
    SUM(CASE WHEN b.user_id IS NULL THEN NULL
        WHEN b.first_repeat_utc <= b.first_purchase_utc + day.day * INTERVAL '1 day'
        THEN 1 ELSE 0 END) AS repeat_users,
    COUNT(b.user_id) FILTER (WHERE b.first_repeat_utc <= b.first_purchase_utc + day.day * INTERVAL '1 day')::DOUBLE
        / NULLIF(COUNT(b.user_id), 0) AS repeat_rate
FROM cohort_definitions d CROSS JOIN days day CROSS JOIN cohort_parameters p
LEFT JOIN cohort_memberships m USING (cohort_id)
LEFT JOIN buyer_history b ON b.user_id = m.user_id
    AND b.first_purchase_utc + p.comparison_horizon_days * INTERVAL '1 day' < p.observation_end_exclusive_utc
WHERE d.family = 'calendar_week'
GROUP BY d.cohort_id, d.cohort_label, day.day;
