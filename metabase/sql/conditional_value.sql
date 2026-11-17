-- Conditional +1 pp scenario, not realized revenue. Grain/key: primary scenario.
SELECT additional_positive_purchase_value AS conditional_value
FROM reporting.experiment_scenarios
WHERE is_primary;
