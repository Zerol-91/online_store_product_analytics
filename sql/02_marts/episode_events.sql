-- Grain: one session-eligible source record. Key: (source_file, source_row_number).
CREATE OR REPLACE TABLE episode_events AS
WITH ordered AS (
    SELECT
        source_file, source_row_number, user_id, user_session, event_time_utc,
        event_type, price,
        LAG(event_time_utc) OVER (
            PARTITION BY user_id, user_session
            ORDER BY event_time_utc, source_file, source_row_number
        ) AS previous_event_utc
    FROM stg_events
    WHERE is_session_eligible
), starts AS (
    SELECT
        *,
        CASE WHEN previous_event_utc IS NULL
            OR event_time_utc - previous_event_utc > p.inactivity_minutes * INTERVAL '1 minute'
            THEN 1 ELSE 0 END AS starts_episode
    FROM ordered
    CROSS JOIN funnel_parameters p
)
SELECT
    source_file, source_row_number, user_id, user_session, event_time_utc, event_type, price,
    SUM(starts_episode) OVER (
        PARTITION BY user_id, user_session
        ORDER BY event_time_utc, source_file, source_row_number
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    )::BIGINT AS episode_number
FROM starts;
