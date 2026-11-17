-- Fixed complete 60-day follow-up populations. Grain/key: cohort/day.
SELECT day, cohort_label AS cohort, repeat_rate
FROM reporting.cohort_curves
ORDER BY day, CASE cohort_id WHEN 'baseline_nov11' THEN 1 WHEN 'baseline_nov18' THEN 2
    WHEN 'black_friday_week' THEN 3 ELSE 4 END;
