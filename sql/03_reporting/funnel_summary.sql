-- Grain: one session definition and timestamp rule. Key: (session_definition, timestamp_rule).
CREATE OR REPLACE TABLE funnel_summary AS
WITH rules AS (
    SELECT * FROM (VALUES ('allow_equal'), ('strict')) AS t(timestamp_rule)
), definitions AS (
    SELECT * FROM (VALUES ('episode_30m'), ('source_key')) AS t(session_definition)
), classified AS (
    SELECT
        d.session_definition, r.timestamp_rule, f.* EXCLUDE (session_definition),
        CASE WHEN r.timestamp_rule = 'allow_equal' THEN cart_after_view_utc
            ELSE strict_cart_after_view_utc END AS qualified_cart_utc,
        CASE WHEN r.timestamp_rule = 'allow_equal' THEN purchase_after_view_cart_utc
            ELSE strict_purchase_after_view_cart_utc END AS qualified_purchase_utc,
        CASE WHEN r.timestamp_rule = 'allow_equal' THEN purchase_after_cart_utc
            ELSE strict_purchase_after_cart_utc END AS cart_purchase_utc
    FROM definitions d CROSS JOIN rules r
    LEFT JOIN session_funnel f USING (session_definition)
), counts AS (
    SELECT
        session_definition, timestamp_rule,
        COUNT(user_id) AS units,
        COUNT(*) FILTER (WHERE view_event_count > 0) AS view_units,
        COUNT(*) FILTER (WHERE cart_event_count > 0) AS cart_units,
        COUNT(*) FILTER (WHERE purchase_event_count > 0) AS purchase_units,
        COUNT(qualified_cart_utc) AS view_cart_units,
        COUNT(qualified_purchase_utc) AS full_chain_units,
        COUNT(cart_purchase_utc) AS cart_purchase_units,
        COUNT(*) FILTER (WHERE cart_event_count > 0 AND cart_purchase_utc IS NULL)
            AS abandoned_cart_units,
        COUNT(*) FILTER (WHERE purchase_event_count > 0 AND qualified_purchase_utc IS NULL)
            AS purchase_units_without_ordered_chain,
        COUNT(*) FILTER (WHERE purchase_event_count > 0 AND cart_event_count = 0)
            AS purchase_units_without_cart,
        COUNT(*) FILTER (WHERE near_observation_start) AS units_near_observation_start,
        COUNT(*) FILTER (WHERE open_at_observation_end) AS units_open_at_observation_end,
        COUNT(*) FILTER (WHERE open_at_observation_end AND cart_event_count > 0
            AND cart_purchase_utc IS NULL) AS abandoned_cart_units_open_at_end,
        COALESCE(SUM(positive_purchase_value), 0) AS positive_purchase_value
    FROM classified
    GROUP BY session_definition, timestamp_rule
)
SELECT
    *,
    view_cart_units::DOUBLE / NULLIF(view_units, 0) AS view_to_cart_rate,
    full_chain_units::DOUBLE / NULLIF(view_cart_units, 0) AS ordered_cart_to_purchase_rate,
    full_chain_units::DOUBLE / NULLIF(view_units, 0) AS ordered_view_to_purchase_rate,
    cart_purchase_units::DOUBLE / NULLIF(cart_units, 0) AS cart_to_purchase_rate,
    abandoned_cart_units::DOUBLE / NULLIF(cart_units, 0) AS cart_abandonment_rate
FROM counts;
