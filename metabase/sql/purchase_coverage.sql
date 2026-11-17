-- Disjoint purchasing-episode coverage. Grain/key: coverage group.
WITH selected AS (
    SELECT full_chain_units, purchase_units_without_ordered_chain
    FROM reporting.funnel_summary
    WHERE session_definition = 'episode_30m' AND timestamp_rule = {{timestamp_rule}}
)
SELECT coverage, episodes
FROM selected CROSS JOIN LATERAL (VALUES
    ('Complete ordered chain', full_chain_units),
    ('Outside complete chain', purchase_units_without_ordered_chain)
) AS groups(coverage, episodes)
ORDER BY coverage;
