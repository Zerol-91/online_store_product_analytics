-- Assumptions and historical sample planning, not an observed experiment. Grain/key: uplift.
SELECT 100 * absolute_uplift AS assumed_uplift_pp, n_per_group AS users_per_arm,
    historical_total_days AS replay_total_days, scenario_population AS eligible_users,
    additional_converted_users, additional_positive_purchase_value AS conditional_value
FROM reporting.experiment_scenarios
ORDER BY absolute_uplift;
