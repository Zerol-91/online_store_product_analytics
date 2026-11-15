-- Count unique historical enrollments without requiring future outcomes. Grain: UTC entry date. Key: entry_date_utc.
CREATE OR REPLACE TABLE cart_experiment_daily AS
WITH days AS (
    SELECT UNNEST(GENERATE_SERIES(entry_start_utc::DATE,
        (observation_end_exclusive_utc - INTERVAL '1 microsecond')::DATE, INTERVAL '1 day'))::DATE AS entry_date_utc
    FROM experiment_parameters
)
SELECT d.entry_date_utc, COUNT(u.user_id) AS enrolled_users,
    COUNT(u.user_id) FILTER (WHERE u.has_complete_window) AS mature_users
FROM days d LEFT JOIN cart_experiment_users u ON u.entry_utc::DATE = d.entry_date_utc
GROUP BY d.entry_date_utc;
