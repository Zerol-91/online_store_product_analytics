-- Establish first and repeat episodes. Grain: one observed purchaser. Key: user_id.
CREATE OR REPLACE TABLE buyer_history AS
WITH ordered AS (
    SELECT *, MIN(first_purchase_utc) OVER (PARTITION BY user_id) AS first_time,
        MAX(last_purchase_utc) OVER (
            PARTITION BY user_id ORDER BY first_purchase_utc, user_session, episode_number
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
        ) AS previous_last_purchase_utc
    FROM purchase_episodes
)
SELECT user_id, MIN(first_time) AS first_purchase_utc,
    MIN(first_purchase_utc) FILTER (WHERE first_purchase_utc > first_time) AS first_repeat_utc,
    COUNT(*) FILTER (WHERE first_purchase_utc = first_time) AS initial_episode_count,
    COUNT(*) AS purchase_episode_count,
    BOOL_OR(COALESCE(first_purchase_utc <= previous_last_purchase_utc, FALSE))
        AS has_overlapping_purchase_episodes
FROM ordered
GROUP BY user_id;
