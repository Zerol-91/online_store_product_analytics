-- Classify visitor history and price. Grain: one cart episode. Key: (user_id, user_session, episode_number).
CREATE OR REPLACE TABLE cart_segments AS
SELECT c.*, u.first_seen_utc,
    CASE WHEN c.session_start_utc = u.first_seen_utc THEN 'first_observed'
        ELSE 'returning' END AS visitor_type,
    CASE WHEN c.entry_price IS NULL OR t.low_upper IS NULL THEN 'unknown'
        WHEN c.entry_price <= t.low_upper THEN 'low'
        WHEN c.entry_price <= t.middle_upper THEN 'middle'
        ELSE 'high' END AS price_band,
    c.session_start_utc >= p.analysis_start_utc AS is_analysis_period
FROM cart_entry_prices c
JOIN users u USING (user_id)
CROSS JOIN price_thresholds t
CROSS JOIN segment_parameters p;
