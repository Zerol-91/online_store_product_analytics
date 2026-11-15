-- Establish observed history. Grain: one valid user. Key: user_id.
CREATE OR REPLACE TABLE users AS
SELECT
    user_id,
    MIN(event_time_utc) AS first_seen_utc,
    MIN(event_time_utc) FILTER (WHERE event_type = 'view') AS first_view_utc,
    MIN(event_time_utc) FILTER (WHERE event_type = 'purchase') AS first_purchase_utc
FROM stg_events
WHERE NOT is_invalid_user_id AND NOT is_invalid_event_time
GROUP BY user_id;
