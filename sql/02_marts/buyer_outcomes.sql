-- Measure complete fixed horizons. Grain: one buyer and horizon. Key: (user_id, horizon_days).
CREATE OR REPLACE TABLE buyer_outcomes AS
WITH windows AS (
    SELECT b.*, h.horizon_days,
        b.first_purchase_utc + h.horizon_days * INTERVAL '1 day' AS deadline_utc,
        b.first_purchase_utc + h.horizon_days * INTERVAL '1 day' < p.observation_end_exclusive_utc
            AS has_complete_window,
        b.first_purchase_utc + p.comparison_horizon_days * INTERVAL '1 day'
            < p.observation_end_exclusive_utc AS has_complete_comparison_window
    FROM buyer_history b CROSS JOIN repurchase_horizons h CROSS JOIN cohort_parameters p
), values_by_window AS (
    SELECT w.user_id, w.horizon_days,
        COALESCE(SUM(e.positive_purchase_value), 0) AS total_positive_purchase_value,
        COALESCE(SUM(e.positive_purchase_value) FILTER (
            WHERE a.first_purchase_utc > w.first_purchase_utc
        ), 0) AS repeat_positive_purchase_value
    FROM windows w
    LEFT JOIN purchase_events e ON e.user_id = w.user_id
        AND e.event_time_utc >= w.first_purchase_utc AND e.event_time_utc <= w.deadline_utc
    LEFT JOIN purchase_episodes a ON a.user_id = e.user_id AND a.user_session = e.user_session
        AND a.episode_number = e.episode_number
    GROUP BY w.user_id, w.horizon_days
)
SELECT w.*,
    CASE WHEN w.has_complete_window THEN COALESCE(w.first_repeat_utc <= w.deadline_utc, FALSE)
        ELSE NULL END AS repeated,
    CASE WHEN w.has_complete_window THEN v.total_positive_purchase_value ELSE NULL END
        AS total_positive_purchase_value,
    CASE WHEN w.has_complete_window THEN v.repeat_positive_purchase_value ELSE NULL END
        AS repeat_positive_purchase_value
FROM windows w JOIN values_by_window v USING (user_id, horizon_days);
