-- Grain: one source record. Key: (source_file, source_row_number).
CREATE OR REPLACE TABLE stg_events AS
WITH counted AS (
    SELECT
        *,
        COUNT(*) OVER (
            PARTITION BY event_time, event_type, product_id, category_id,
                category_code, brand, price, user_id, user_session
        ) AS duplicate_group_size
    FROM raw_events
), parsed AS (
    SELECT
        source_file,
        source_row_number,
        TRY_CAST(event_time AS TIMESTAMPTZ) AS parsed_time,
        event_type,
        CASE WHEN REGEXP_FULL_MATCH(TRIM(product_id), '[0-9]+')
            THEN TRY_CAST(product_id AS BIGINT) END AS product_id,
        CASE WHEN REGEXP_FULL_MATCH(TRIM(category_id), '[0-9]+')
            THEN TRY_CAST(category_id AS BIGINT) END AS category_id,
        category_code,
        brand,
        CASE WHEN TRY_CAST(price AS DECIMAL(24, 6)) = TRY_CAST(price AS DOUBLE)
            THEN TRY_CAST(price AS DECIMAL(24, 6)) END AS price,
        CASE WHEN REGEXP_FULL_MATCH(TRIM(user_id), '[0-9]+')
            THEN TRY_CAST(user_id AS BIGINT) END AS user_id,
        NULLIF(TRIM(user_session), '') AS user_session,
        duplicate_group_size
    FROM counted
), typed AS (
    SELECT
        * EXCLUDE (parsed_time),
        CASE WHEN ISFINITE(parsed_time)
            THEN parsed_time AT TIME ZONE 'UTC' END AS event_time_utc
    FROM parsed
)
SELECT
    *,
    duplicate_group_size > 1 AS is_in_duplicate_group,
    user_id IS NULL AS is_invalid_user_id,
    product_id IS NULL AS is_invalid_product_id,
    category_id IS NULL AS is_invalid_category_id,
    user_session IS NULL AS is_missing_user_session,
    event_time_utc IS NULL AS is_invalid_event_time,
    price IS NULL AS is_invalid_price,
    COALESCE(price <= 0, FALSE) AS is_nonpositive_price,
    COALESCE(event_type NOT IN ('view', 'cart', 'remove_from_cart', 'purchase'), TRUE)
        AS is_unknown_event_type,
    user_id IS NOT NULL AND user_session IS NOT NULL AND event_time_utc IS NOT NULL
        AS is_session_eligible
FROM typed;
