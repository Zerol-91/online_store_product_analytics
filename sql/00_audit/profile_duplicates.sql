-- Purpose: measure sensitivity to exact-row deduplication; do not remove rows.
-- Grain: one row per event_type. Key: event_type, including a NULL group.
-- All nine original string fields define a duplicate; ingestion metadata does not.
-- Price sums are diagnostic event values, not orders, profit, or causal losses.
WITH row_groups AS (
    SELECT
        event_time,
        event_type,
        product_id,
        category_id,
        category_code,
        brand,
        price,
        user_id,
        user_session,
        COUNT(*) AS copies
    FROM raw_events
    GROUP BY ALL
), priced AS (
    SELECT
        *,
        TRY_CAST(price AS DECIMAL(24, 6)) AS numeric_price
    FROM row_groups
)
SELECT
    event_type,
    SUM(copies) AS row_count,
    COUNT(*) AS unique_rows,
    SUM(copies - 1) AS duplicate_rows,
    COUNT(*) FILTER (WHERE copies > 1) AS duplicate_groups,
    COALESCE(SUM(copies) FILTER (WHERE copies > 1), 0) AS rows_in_duplicate_groups,
    CAST(SUM(CASE WHEN numeric_price > 0 THEN numeric_price * copies ELSE 0 END) AS VARCHAR)
        AS positive_price_value_before_dedup,
    CAST(SUM(CASE WHEN numeric_price > 0 THEN numeric_price ELSE 0 END) AS VARCHAR)
        AS positive_price_value_after_dedup,
    COUNT(*) FILTER (
        WHERE numeric_price IS NOT NULL AND numeric_price != TRY_CAST(price AS DOUBLE)
    ) AS price_precision_mismatch_groups
FROM priced
GROUP BY event_type
ORDER BY event_type NULLS FIRST;
