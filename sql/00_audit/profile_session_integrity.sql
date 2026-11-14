-- Grain: one summary row for the built session table; thresholds are diagnostic only.
WITH token_users AS (
    SELECT user_session, COUNT(*) AS users_per_token
    FROM sessions
    GROUP BY user_session
), event_times AS (
    SELECT DISTINCT user_id, user_session, event_time_utc
    FROM stg_events
    WHERE is_session_eligible
), event_gaps AS (
    SELECT
        user_id,
        user_session,
        event_time_utc - LAG(event_time_utc) OVER (
            PARTITION BY user_id, user_session ORDER BY event_time_utc
        ) AS event_gap
    FROM event_times
), fragment_counts AS (
    SELECT
        user_id,
        user_session,
        COUNT(*) FILTER (WHERE event_gap > INTERVAL '30 minutes') AS additional_fragments
    FROM event_gaps
    GROUP BY user_id, user_session
), fragment_summary AS (
    SELECT
        COUNT(*) FILTER (WHERE additional_fragments > 0) AS source_sessions_with_gap_over_30m,
        COALESCE(SUM(additional_fragments), 0) AS additional_fragments_at_30m
    FROM fragment_counts
), purchase_times AS (
    SELECT DISTINCT user_id, user_session, event_time_utc
    FROM stg_events
    WHERE is_session_eligible AND event_type = 'purchase'
), purchase_gaps AS (
    SELECT
        *,
        event_time_utc - LAG(event_time_utc) OVER (
            PARTITION BY user_id, user_session ORDER BY event_time_utc
        ) AS purchase_gap
    FROM purchase_times
), purchase_sessions AS (
    SELECT
        user_id,
        user_session,
        BOOL_OR(purchase_gap > INTERVAL '30 minutes') AS has_gap_over_30m,
        BOOL_OR(purchase_gap > INTERVAL '24 hours') AS has_gap_over_24h
    FROM purchase_gaps
    GROUP BY user_id, user_session
), token_summary AS (
    SELECT
        COUNT(*) FILTER (WHERE users_per_token > 1) AS tokens_shared_across_users,
        COALESCE(SUM(users_per_token) FILTER (WHERE users_per_token > 1), 0)
            AS sessions_with_shared_token
    FROM token_users
), purchase_summary AS (
    SELECT
        COUNT(*) FILTER (WHERE has_gap_over_30m) AS purchase_sessions_with_gap_over_30m,
        COUNT(*) FILTER (WHERE has_gap_over_24h) AS purchase_sessions_with_gap_over_24h
    FROM purchase_sessions
), session_summary AS (
    SELECT
        COUNT(*) AS session_count,
        COUNT(DISTINCT user_id) AS session_user_count,
        COUNT(*) FILTER (WHERE has_purchase) AS purchase_session_count,
        COUNT(*) FILTER (WHERE source_file_count > 1) AS sessions_in_multiple_files,
        COUNT(*) FILTER (
            WHERE DATE_TRUNC('month', session_start_utc) != DATE_TRUNC('month', session_end_utc)
        ) AS sessions_crossing_months,
        COUNT(*) FILTER (WHERE duration_seconds > 86400) AS sessions_longer_than_24h,
        COUNT(*) FILTER (WHERE duration_seconds > 604800) AS sessions_longer_than_7d,
        COUNT(*) FILTER (WHERE purchase_timestamp_count > 1)
            AS sessions_with_multiple_purchase_timestamps,
        QUANTILE_CONT(duration_seconds, 0.5) AS median_duration_seconds,
        QUANTILE_CONT(duration_seconds, 0.99) AS p99_duration_seconds,
        MAX(duration_seconds) AS max_duration_seconds
    FROM sessions
)
SELECT *
FROM session_summary
CROSS JOIN token_summary
CROSS JOIN purchase_summary
CROSS JOIN fragment_summary;
