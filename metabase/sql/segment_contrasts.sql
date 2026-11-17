-- Prespecified B-minus-A contrasts; Bonferroni 97.5% intervals. Grain/key: family.
SELECT family, group_b || ' minus ' || group_a AS comparison,
    100 * estimate AS difference_pp, 100 * ci_low AS ci_low_pp, 100 * ci_high AS ci_high_pp,
    CASE WHEN adjusted_p_value = 0 THEN 'Below numeric precision'
        ELSE TRIM(TO_CHAR(adjusted_p_value, '0.00EEEE')) END AS adjusted_p_value
FROM reporting.cart_segment_contrasts
ORDER BY family DESC;
