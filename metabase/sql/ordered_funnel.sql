-- Ordered episode stages, not all carts. Grain/key: stage number.
WITH selected AS (
    SELECT view_units, view_cart_units, full_chain_units
    FROM reporting.funnel_summary
    WHERE session_definition = 'episode_30m' AND timestamp_rule = {{timestamp_rule}}
)
SELECT stage, episodes
FROM selected CROSS JOIN LATERAL (VALUES
    ('1. Recorded view', view_units),
    ('2. Cart after view', view_cart_units),
    ('3. Purchase after cart', full_chain_units)
) AS stages(stage, episodes)
ORDER BY stage;
