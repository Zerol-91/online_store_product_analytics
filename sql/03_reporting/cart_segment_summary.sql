-- Summarize episode conversion. Grain: one segment. Key: (family, segment).
CREATE OR REPLACE TABLE cart_segment_summary AS
SELECT family, segment, COUNT(*) AS users, SUM(episodes) AS episodes,
    SUM(conversions) AS conversions, SUM(open_episodes) AS open_episodes,
    SUM(conversions)::DOUBLE / SUM(episodes) AS conversion_rate
FROM cart_segment_users
GROUP BY family, segment;
