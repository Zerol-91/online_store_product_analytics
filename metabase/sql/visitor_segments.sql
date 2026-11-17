-- November onward cart episodes by observed history. Grain/key: visitor segment.
SELECT CASE segment WHEN 'first_observed' THEN 'First observed' ELSE 'Returning' END AS segment,
    conversion_rate AS conversion
FROM reporting.cart_segment_summary
WHERE family = 'visitor_type'
ORDER BY CASE segment WHEN 'first_observed' THEN 1 ELSE 2 END;
