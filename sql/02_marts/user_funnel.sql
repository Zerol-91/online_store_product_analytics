-- Attach fixed-window outcomes. Grain: one observed user. Key: user_id. Deadline is inclusive.
CREATE OR REPLACE TABLE user_funnel AS
SELECT
    u.*,
    u.first_view_utc + p.horizon_days * INTERVAL '1 day' AS window_end_utc,
    COALESCE(u.first_view_utc + p.horizon_days * INTERVAL '1 day'
        < p.observation_end_exclusive_utc, FALSE) AS has_complete_window,
    COALESCE(u.first_view_utc >= p.analysis_start_utc, FALSE) AS enters_after_warmup,
    COALESCE(u.first_view_utc >= p.analysis_start_utc
        AND u.first_view_utc + p.horizon_days * INTERVAL '1 day'
            < p.observation_end_exclusive_utc, FALSE) AS is_primary_eligible,
    f.cart_after_view_utc,
    f.purchase_after_view_cart_utc,
    f.strict_cart_after_view_utc,
    f.strict_purchase_after_view_cart_utc,
    COALESCE(f.purchase_event_count, 0) > 0 AS has_purchase_in_window
FROM users u
CROSS JOIN segment_parameters p
LEFT JOIN funnel_result f USING (user_id);
