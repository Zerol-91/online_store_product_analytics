-- Grain: one observed (user_id, user_session) pair. Counts do not establish event order.
CREATE OR REPLACE TABLE sessions AS
SELECT
    user_id,
    user_session,
    MIN(event_time_utc) AS session_start_utc,
    MAX(event_time_utc) AS session_end_utc,
    DATE_DIFF('second', MIN(event_time_utc), MAX(event_time_utc)) AS duration_seconds,
    COUNT(*) AS event_count,
    COUNT(DISTINCT source_file) AS source_file_count,
    COUNT(*) FILTER (WHERE event_type = 'view') AS view_event_count,
    COUNT(*) FILTER (WHERE event_type = 'cart') AS cart_event_count,
    COUNT(*) FILTER (WHERE event_type = 'remove_from_cart') AS remove_event_count,
    COUNT(*) FILTER (WHERE event_type = 'purchase') AS purchase_event_count,
    COALESCE(BOOL_OR(event_type = 'view'), FALSE) AS has_view,
    COALESCE(BOOL_OR(event_type = 'cart'), FALSE) AS has_cart,
    COALESCE(BOOL_OR(event_type = 'purchase'), FALSE) AS has_purchase,
    MIN(event_time_utc) FILTER (WHERE event_type = 'purchase') AS first_purchase_utc,
    MAX(event_time_utc) FILTER (WHERE event_type = 'purchase') AS last_purchase_utc,
    COUNT(DISTINCT event_time_utc) FILTER (WHERE event_type = 'purchase')
        AS purchase_timestamp_count,
    SUM(CASE WHEN event_type = 'purchase' AND price > 0 THEN price ELSE 0 END)
        AS positive_purchase_value,
    COUNT(*) FILTER (WHERE event_type = 'purchase' AND is_nonpositive_price)
        AS nonpositive_purchase_event_count,
    COUNT(*) FILTER (WHERE event_type = 'purchase' AND is_invalid_price)
        AS invalid_price_purchase_event_count
FROM stg_events
WHERE is_session_eligible
GROUP BY user_id, user_session;
