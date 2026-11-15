-- Summarize user journeys. Grain: one population and timestamp rule. Key: (population, timestamp_rule).
CREATE OR REPLACE TABLE user_funnel_summary AS
WITH populations AS (
    SELECT * FROM (VALUES ('post_warmup'), ('all_mature_first_views')) AS t(population)
), rules AS (
    SELECT * FROM (VALUES ('allow_equal'), ('strict')) AS t(timestamp_rule)
), classified AS (
    SELECT
        p.population, r.timestamp_rule, u.user_id, u.has_purchase_in_window,
        CASE WHEN r.timestamp_rule = 'allow_equal' THEN u.cart_after_view_utc
            ELSE u.strict_cart_after_view_utc END AS cart_utc,
        CASE WHEN r.timestamp_rule = 'allow_equal' THEN u.purchase_after_view_cart_utc
            ELSE u.strict_purchase_after_view_cart_utc END AS purchase_utc
    FROM populations p CROSS JOIN rules r
    LEFT JOIN user_funnel u ON CASE WHEN p.population = 'post_warmup'
        THEN u.is_primary_eligible ELSE u.has_complete_window END
), counts AS (
    SELECT population, timestamp_rule, COUNT(user_id) AS view_users,
        COUNT(cart_utc) AS cart_users, COUNT(purchase_utc) AS full_chain_users,
        COUNT(*) FILTER (WHERE has_purchase_in_window) AS purchase_users
    FROM classified
    GROUP BY population, timestamp_rule
)
SELECT *, cart_users::DOUBLE / NULLIF(view_users, 0) AS view_to_cart_rate,
    full_chain_users::DOUBLE / NULLIF(cart_users, 0) AS cart_to_purchase_rate,
    full_chain_users::DOUBLE / NULLIF(view_users, 0) AS view_to_purchase_rate,
    purchase_users - full_chain_users AS purchase_users_without_full_chain
FROM counts;
