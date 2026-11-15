-- Grain: one input unit. Key: (user_id, user_session, episode_number).
CREATE OR REPLACE TEMP TABLE funnel_result AS
WITH base AS (
    SELECT
        user_id, user_session, episode_number,
        MIN(event_time_utc) AS session_start_utc,
        MAX(event_time_utc) AS session_end_utc,
        COUNT(*) AS event_count,
        COUNT(*) FILTER (WHERE event_type = 'view') AS view_event_count,
        COUNT(*) FILTER (WHERE event_type = 'cart') AS cart_event_count,
        COUNT(*) FILTER (WHERE event_type = 'purchase') AS purchase_event_count,
        MIN(event_time_utc) FILTER (WHERE event_type = 'view') AS first_view_utc,
        MIN(event_time_utc) FILTER (WHERE event_type = 'cart') AS first_cart_utc,
        SUM(CASE WHEN event_type = 'purchase' AND price > 0 THEN price ELSE 0 END)
            AS positive_purchase_value
    FROM funnel_input
    GROUP BY user_id, user_session, episode_number
), cart_steps AS (
    SELECT
        e.user_id, e.user_session, e.episode_number,
        MIN(e.event_time_utc) FILTER (
            WHERE e.event_type = 'cart' AND e.event_time_utc >= b.first_view_utc
        ) AS cart_after_view_utc,
        MIN(e.event_time_utc) FILTER (
            WHERE e.event_type = 'cart' AND e.event_time_utc > b.first_view_utc
        ) AS strict_cart_after_view_utc
    FROM funnel_input e
    JOIN base b USING (user_id, user_session, episode_number)
    GROUP BY e.user_id, e.user_session, e.episode_number
), purchase_steps AS (
    SELECT
        e.user_id, e.user_session, e.episode_number,
        MIN(e.event_time_utc) FILTER (
            WHERE e.event_type = 'purchase' AND e.event_time_utc >= c.cart_after_view_utc
        ) AS purchase_after_view_cart_utc,
        MIN(e.event_time_utc) FILTER (
            WHERE e.event_type = 'purchase' AND e.event_time_utc > c.strict_cart_after_view_utc
        ) AS strict_purchase_after_view_cart_utc,
        MIN(e.event_time_utc) FILTER (
            WHERE e.event_type = 'purchase' AND e.event_time_utc >= b.first_cart_utc
        ) AS purchase_after_cart_utc,
        MIN(e.event_time_utc) FILTER (
            WHERE e.event_type = 'purchase' AND e.event_time_utc > b.first_cart_utc
        ) AS strict_purchase_after_cart_utc
    FROM funnel_input e
    JOIN base b USING (user_id, user_session, episode_number)
    JOIN cart_steps c USING (user_id, user_session, episode_number)
    GROUP BY e.user_id, e.user_session, e.episode_number
)
SELECT
    b.*, c.* EXCLUDE (user_id, user_session, episode_number),
    p.* EXCLUDE (user_id, user_session, episode_number),
    b.session_start_utc < settings.observation_start_utc
        + settings.inactivity_minutes * INTERVAL '1 minute' AS near_observation_start,
    b.session_end_utc + settings.inactivity_minutes * INTERVAL '1 minute'
        >= settings.observation_end_exclusive_utc AS open_at_observation_end
FROM base b
JOIN cart_steps c USING (user_id, user_session, episode_number)
JOIN purchase_steps p USING (user_id, user_session, episode_number)
CROSS JOIN funnel_parameters settings;
