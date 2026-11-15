-- Separate calendar-month repurchasing from elapsed days. Grain: cohort/month age. Key: (cohort_id, month_age).
CREATE OR REPLACE TABLE monthly_repurchase AS
WITH grid AS (
    SELECT d.*, a.month_age,
        DATE_TRUNC('month', d.entry_start_utc) + a.month_age * INTERVAL '1 month' AS target_start_utc,
        DATE_TRUNC('month', d.entry_start_utc) + (a.month_age + 1) * INTERVAL '1 month' AS target_end_exclusive_utc
    FROM cohort_definitions d CROSS JOIN calendar_month_ages a WHERE d.family = 'calendar_month'
), counts AS (
    SELECT g.*, COUNT(DISTINCT m.user_id) AS cohort_users,
        COUNT(DISTINCT b.user_id) FILTER (WHERE a.user_id IS NOT NULL) AS observed_repeat_users
    FROM grid g LEFT JOIN cohort_memberships m USING (cohort_id)
    LEFT JOIN buyer_history b USING (user_id)
    LEFT JOIN purchase_episodes a ON a.user_id = b.user_id AND a.first_purchase_utc > b.first_purchase_utc
        AND a.first_purchase_utc >= g.target_start_utc AND a.first_purchase_utc < g.target_end_exclusive_utc
    GROUP BY ALL
)
SELECT c.* EXCLUDE (observed_repeat_users),
    c.target_end_exclusive_utc <= p.observation_end_exclusive_utc AS has_complete_month,
    CASE WHEN c.target_end_exclusive_utc <= p.observation_end_exclusive_utc THEN c.observed_repeat_users
        ELSE NULL END AS repeat_users,
    CASE WHEN c.target_end_exclusive_utc <= p.observation_end_exclusive_utc
        THEN c.observed_repeat_users::DOUBLE / NULLIF(c.cohort_users, 0) ELSE NULL END AS repeat_rate
FROM counts c CROSS JOIN cohort_parameters p;
