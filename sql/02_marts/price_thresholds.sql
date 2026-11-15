-- Freeze price-only cutpoints. Grain: one configured reference period. Key: singleton row.
CREATE OR REPLACE TABLE price_thresholds AS
SELECT COUNT(c.entry_price) AS reference_priced_episodes,
    CAST(ROUND(QUANTILE_CONT(c.entry_price::DOUBLE, 1.0 / 3), 6) AS DECIMAL(24, 6)) AS low_upper,
    CAST(ROUND(QUANTILE_CONT(c.entry_price::DOUBLE, 2.0 / 3), 6) AS DECIMAL(24, 6)) AS middle_upper
FROM cart_entry_prices c
CROSS JOIN segment_parameters p
WHERE c.first_cart_utc >= p.price_reference_start_utc
    AND c.first_cart_utc < p.price_reference_end_exclusive_utc;
