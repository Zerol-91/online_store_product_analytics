-- Audit purchase proxies and source coverage. Grain: one audit result. Key: singleton row.
WITH ordered AS (
    SELECT *, MAX(last_purchase_utc) OVER (
        PARTITION BY user_id ORDER BY first_purchase_utc, user_session, episode_number
        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
    ) AS previous_last,
    LAG(first_purchase_utc) OVER (
        PARTITION BY user_id ORDER BY first_purchase_utc, user_session, episode_number
    ) AS previous_first
    FROM purchase_episodes
), ties AS (
    SELECT user_id, first_purchase_utc, COUNT(*) AS episodes
    FROM purchase_episodes GROUP BY user_id, first_purchase_utc HAVING COUNT(*) > 1
)
SELECT COUNT(*) AS purchase_episodes, COUNT(DISTINCT user_id) AS purchasers,
    COALESCE(SUM(purchase_event_count), 0) AS purchase_events,
    COALESCE(SUM(positive_purchase_value), 0) AS positive_purchase_value,
    COUNT(*) FILTER (WHERE purchase_timestamp_count > 1) AS multi_timestamp_episodes,
    MAX(EPOCH(last_purchase_utc - first_purchase_utc)) AS maximum_purchase_span_seconds,
    COUNT(*) FILTER (WHERE first_purchase_utc <= previous_last) AS overlapping_or_tied_episodes,
    COUNT(DISTINCT user_id) FILTER (WHERE first_purchase_utc <= previous_last) AS overlap_users,
    COUNT(*) FILTER (WHERE first_purchase_utc > previous_first
        AND first_purchase_utc <= previous_first + INTERVAL '30 minutes') AS close_episode_pairs,
    (SELECT COUNT(*) FROM ties) AS simultaneous_episode_start_groups,
    (SELECT COALESCE(SUM(episodes), 0) FROM ties) AS simultaneous_start_episodes,
    (SELECT COUNT(*) FROM buyer_history WHERE initial_episode_count > 1) AS initial_tie_users,
    (SELECT COUNT(*) FROM stg_events WHERE event_type = 'purchase' AND NOT is_session_eligible)
        AS uncovered_purchase_events,
    (SELECT COUNT(*) FROM stg_events WHERE event_type = 'purchase') AS source_purchase_events
FROM ordered;
