-- Price the first cart timestamp. Grain: one cart episode. Key: (user_id, user_session, episode_number).
CREATE OR REPLACE TABLE cart_entry_prices AS
WITH entry_items AS (
    SELECT e.user_id, e.user_session, e.episode_number, s.product_id,
        MEDIAN(DISTINCT e.price) AS price
    FROM episode_events e
    JOIN episodes a USING (user_id, user_session, episode_number)
    JOIN stg_events s USING (source_file, source_row_number)
    WHERE e.event_type = 'cart' AND e.event_time_utc = a.first_cart_utc AND e.price > 0
    GROUP BY e.user_id, e.user_session, e.episode_number, s.product_id
), entry_prices AS (
    SELECT user_id, user_session, episode_number,
        MEDIAN(price) AS entry_price, COUNT(*) AS priced_entry_items
    FROM entry_items
    GROUP BY user_id, user_session, episode_number
)
SELECT a.user_id, a.user_session, a.episode_number, a.session_start_utc,
    a.first_cart_utc, a.open_at_observation_end,
    CASE WHEN settings.primary_timestamp_rule = 'strict' THEN a.strict_purchase_after_cart_utc
        ELSE a.purchase_after_cart_utc END IS NOT NULL AS converted,
    p.entry_price, COALESCE(p.priced_entry_items, 0) AS priced_entry_items
FROM episodes a
LEFT JOIN entry_prices p USING (user_id, user_session, episode_number)
CROSS JOIN segment_parameters settings
WHERE a.cart_event_count > 0;
