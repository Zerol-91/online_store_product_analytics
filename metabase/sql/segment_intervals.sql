-- Existing user-clustered descriptive 95% intervals. Grain/key: family/segment.
SELECT family, segment, episodes AS cart_episodes, conversions AS converted_episodes,
    clusters AS users, estimate AS conversion, ci_low, ci_high
FROM reporting.cart_segment_estimates
ORDER BY family DESC, CASE segment WHEN 'first_observed' THEN 1 WHEN 'returning' THEN 2
    WHEN 'low' THEN 1 WHEN 'middle' THEN 2 WHEN 'high' THEN 3 ELSE 4 END;
