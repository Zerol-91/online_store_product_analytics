-- Cart-entry price bands frozen in October. Grain/key: price segment.
SELECT CASE segment WHEN 'unknown' THEN 'Unknown' ELSE INITCAP(segment) END AS segment,
    CASE WHEN segment IN ('low', 'middle') THEN conversion_rate END AS conversion,
    CASE WHEN segment = 'high' THEN conversion_rate END AS highlighted_conversion,
    CASE WHEN segment = 'unknown' THEN conversion_rate END AS unknown_conversion
FROM reporting.cart_segment_summary
WHERE family = 'price_band'
ORDER BY CASE segment WHEN 'low' THEN 1 WHEN 'middle' THEN 2 WHEN 'high' THEN 3 ELSE 4 END;
