-- Calendar M1/M2, never elapsed 30/60 days. Grain/key: first-purchase month.
SELECT cohort_label AS first_purchase_month, MAX(cohort_users) AS cohort_users,
    CASE WHEN BOOL_AND(has_complete_month) THEN 'M1 + M2 complete'
        WHEN BOOL_OR(has_complete_month) THEN 'M1 complete; M2 NA'
        ELSE 'M1 + M2 NA' END AS follow_up,
    MAX(repeat_rate) FILTER (WHERE month_age = 1) AS m1,
    MAX(repeat_rate) FILTER (WHERE month_age = 2) AS m2
FROM reporting.monthly_repurchase
WHERE 1 = 1 [[AND cohort_label = {{first_purchase_month}}]]
GROUP BY cohort_label
ORDER BY cohort_label;
