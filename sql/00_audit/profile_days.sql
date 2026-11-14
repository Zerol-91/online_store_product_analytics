-- Purpose: check daily event coverage without filtering invalid timestamps.
-- Grain: one row per UTC date; NULL collects missing/invalid timestamps.
-- Key: event_date_utc.
SELECT
    CAST(TRY_CAST(event_time AS TIMESTAMPTZ) AT TIME ZONE 'UTC' AS DATE) AS event_date_utc,
    COUNT(*) AS row_count
FROM raw_events
GROUP BY event_date_utc
ORDER BY event_date_utc NULLS FIRST;
