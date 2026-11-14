-- Purpose: profile unmodified CSV events, including invalid and missing values.
-- Grain: one row per event_type, plus one overall summary row.
-- Key: (is_summary, event_type); NULL event types remain a separate group.
WITH parsed AS (
    SELECT
        *,
        TRY_CAST(NULLIF(TRIM(event_time), '') AS TIMESTAMPTZ) AS parsed_time,
        TRY_CAST(NULLIF(TRIM(price), '') AS DOUBLE) AS parsed_price
    FROM raw_events
)
SELECT
    GROUPING(event_type) AS is_summary,
    event_type,
    COUNT(*) AS row_count,
    MIN(parsed_time AT TIME ZONE 'UTC') AS first_event_utc,
    MAX(parsed_time AT TIME ZONE 'UTC') AS last_event_utc,
    COUNT(*) FILTER (WHERE NULLIF(TRIM(event_time), '') IS NULL) AS missing_event_time,
    COUNT(*) FILTER (WHERE NULLIF(TRIM(event_type), '') IS NULL) AS missing_event_type,
    COUNT(*) FILTER (WHERE NULLIF(TRIM(product_id), '') IS NULL) AS missing_product_id,
    COUNT(*) FILTER (WHERE NULLIF(TRIM(category_id), '') IS NULL) AS missing_category_id,
    COUNT(*) FILTER (WHERE NULLIF(TRIM(category_code), '') IS NULL) AS missing_category_code,
    COUNT(*) FILTER (WHERE NULLIF(TRIM(brand), '') IS NULL) AS missing_brand,
    COUNT(*) FILTER (WHERE NULLIF(TRIM(price), '') IS NULL) AS missing_price,
    COUNT(*) FILTER (WHERE NULLIF(TRIM(user_id), '') IS NULL) AS missing_user_id,
    COUNT(*) FILTER (WHERE NULLIF(TRIM(user_session), '') IS NULL) AS missing_user_session,
    COUNT(*) FILTER (
        WHERE NULLIF(TRIM(event_time), '') IS NOT NULL AND parsed_time IS NULL
    ) AS invalid_event_time,
    COUNT(*) FILTER (
        WHERE NULLIF(TRIM(price), '') IS NOT NULL
            AND (parsed_price IS NULL OR NOT ISFINITE(parsed_price))
    ) AS invalid_price,
    COUNT(*) FILTER (WHERE ISFINITE(parsed_price) AND parsed_price = 0) AS zero_price,
    COUNT(*) FILTER (WHERE ISFINITE(parsed_price) AND parsed_price < 0) AS negative_price,
    COUNT(*) FILTER (
        WHERE NULLIF(TRIM(event_type), '') IS NOT NULL
            AND event_type NOT IN ('view', 'cart', 'remove_from_cart', 'purchase')
    ) AS unexpected_event_type
FROM parsed
GROUP BY GROUPING SETS ((event_type), ())
ORDER BY is_summary DESC, event_type NULLS FIRST;
