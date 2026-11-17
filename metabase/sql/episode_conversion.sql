-- Episode cart conversion. Grain/key: one selected timestamp rule.
SELECT cart_to_purchase_rate AS conversion
FROM reporting.funnel_summary
WHERE session_definition = 'episode_30m' AND timestamp_rule = {{timestamp_rule}};
