-- Report mature post-cart outcomes and tie sensitivity. Grain: timestamp rule. Key: timestamp_rule.
CREATE OR REPLACE TABLE cart_experiment_summary AS
WITH rules AS (
    SELECT UNNEST(['allow_equal', 'strict']) AS timestamp_rule
), classified AS (
    SELECT r.timestamp_rule, u.user_id, u.had_cart_before_period,
        CASE WHEN r.timestamp_rule = 'allow_equal' THEN u.converted ELSE u.strict_converted END AS converted,
        CASE WHEN r.timestamp_rule = 'allow_equal' THEN u.positive_purchase_value
            ELSE u.strict_positive_purchase_value END AS positive_purchase_value
    FROM rules r LEFT JOIN cart_experiment_users u ON u.has_complete_window
)
SELECT timestamp_rule, COUNT(user_id) AS eligible_users,
    SUM(converted::INTEGER) AS converted_users, AVG(converted::INTEGER) AS conversion_rate,
    SUM(positive_purchase_value) AS positive_purchase_value,
    AVG(positive_purchase_value) AS mean_value_per_user,
    MEDIAN(positive_purchase_value) AS median_value_per_user,
    STDDEV_SAMP(positive_purchase_value) AS sd_value_per_user,
    QUANTILE_CONT(positive_purchase_value, 0.95) AS p95_value_per_user,
    QUANTILE_CONT(positive_purchase_value, 0.99) AS p99_value_per_user,
    MAX(positive_purchase_value) AS max_value_per_user,
    AVG(positive_purchase_value) FILTER (WHERE converted) AS mean_value_per_converted_user,
    COUNT(*) FILTER (WHERE had_cart_before_period) AS users_with_preperiod_cart
FROM classified GROUP BY timestamp_rule;
