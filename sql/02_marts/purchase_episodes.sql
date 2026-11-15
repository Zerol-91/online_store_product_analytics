-- Construct order proxies. Grain: one purchase episode. Key: (user_id, user_session, episode_number).
CREATE OR REPLACE TABLE purchase_episodes AS
SELECT user_id, user_session, episode_number,
    MIN(event_time_utc) AS first_purchase_utc,
    MAX(event_time_utc) AS last_purchase_utc,
    COUNT(*) AS purchase_event_count,
    COUNT(DISTINCT event_time_utc) AS purchase_timestamp_count,
    SUM(positive_purchase_value) AS positive_purchase_value,
    COUNT(*) FILTER (WHERE price IS NULL OR price <= 0) AS nonpositive_or_missing_price_events
FROM purchase_events
GROUP BY user_id, user_session, episode_number;
