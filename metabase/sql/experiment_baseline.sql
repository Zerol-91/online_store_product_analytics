-- Seven-day experimental eligibility proxy. Grain/key: primary timestamp rule.
SELECT conversion_rate AS conversion
FROM reporting.cart_experiment_summary
WHERE timestamp_rule = 'allow_equal';
