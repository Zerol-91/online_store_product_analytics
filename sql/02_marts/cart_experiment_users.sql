-- Anchor one experimental entry per user. Grain: cart user in the analysis period. Key: user_id.
CREATE OR REPLACE TABLE cart_experiment_users AS
WITH cart_history AS (
    SELECT e.user_id, MIN(e.event_time_utc) AS first_observed_cart_utc,
        MIN(e.event_time_utc) FILTER (WHERE e.event_time_utc >= p.entry_start_utc
            AND e.event_time_utc < p.observation_end_exclusive_utc) AS entry_utc
    FROM stg_events e CROSS JOIN experiment_parameters p
    WHERE e.event_type = 'cart' AND NOT e.is_invalid_user_id AND NOT e.is_invalid_event_time
    GROUP BY e.user_id
), windows AS (
    SELECT h.*, h.entry_utc + p.horizon_days * INTERVAL '1 day' AS deadline_utc,
        h.entry_utc + p.horizon_days * INTERVAL '1 day' < p.observation_end_exclusive_utc AS has_complete_window,
        h.first_observed_cart_utc < p.entry_start_utc AS had_cart_before_period
    FROM cart_history h CROSS JOIN experiment_parameters p WHERE h.entry_utc IS NOT NULL
), outcomes AS (
    SELECT w.user_id, MIN(e.event_time_utc) AS purchase_utc,
        MIN(e.event_time_utc) FILTER (WHERE e.event_time_utc > w.entry_utc) AS strict_purchase_utc,
        COALESCE(SUM(CASE WHEN e.price > 0 THEN e.price ELSE 0 END), 0) AS positive_purchase_value,
        COALESCE(SUM(CASE WHEN e.price > 0 THEN e.price ELSE 0 END)
            FILTER (WHERE e.event_time_utc > w.entry_utc), 0) AS strict_positive_purchase_value
    FROM windows w LEFT JOIN stg_events e ON e.user_id = w.user_id
        AND e.event_type = 'purchase' AND NOT e.is_invalid_user_id AND NOT e.is_invalid_event_time
        AND e.event_time_utc >= w.entry_utc AND e.event_time_utc <= w.deadline_utc
    GROUP BY w.user_id
)
SELECT w.*, o.purchase_utc, o.strict_purchase_utc,
    CASE WHEN w.has_complete_window THEN o.purchase_utc IS NOT NULL ELSE NULL END AS converted,
    CASE WHEN w.has_complete_window THEN o.strict_purchase_utc IS NOT NULL ELSE NULL END AS strict_converted,
    CASE WHEN w.has_complete_window THEN o.positive_purchase_value ELSE NULL END AS positive_purchase_value,
    CASE WHEN w.has_complete_window THEN o.strict_positive_purchase_value ELSE NULL END AS strict_positive_purchase_value
FROM windows w JOIN outcomes o USING (user_id);
