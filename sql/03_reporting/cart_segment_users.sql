-- Supply cluster counts. Grain: one user within a segment. Key: (family, segment, user_id).
CREATE OR REPLACE TABLE cart_segment_users AS
WITH labeled AS (
    SELECT user_id, 'visitor_type' AS family, visitor_type AS segment,
        converted, open_at_observation_end
    FROM cart_segments WHERE is_analysis_period
    UNION ALL
    SELECT user_id, 'price_band' AS family, price_band AS segment,
        converted, open_at_observation_end
    FROM cart_segments WHERE is_analysis_period
)
SELECT family, segment, user_id, COUNT(*) AS episodes,
    COUNT(*) FILTER (WHERE converted) AS conversions,
    COUNT(*) FILTER (WHERE open_at_observation_end) AS open_episodes
FROM labeled
GROUP BY family, segment, user_id;
