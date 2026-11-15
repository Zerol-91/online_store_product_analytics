-- Compare horizons with explicit maturity populations. Grain: cohort/horizon/population. Key: all three.
CREATE OR REPLACE TABLE cohort_summary AS
WITH populations AS (
    SELECT UNNEST(['horizon_mature', 'common_horizon', 'common_horizon_no_overlap']) AS population
), grid AS (
    SELECT d.*, h.horizon_days, p.population
    FROM cohort_definitions d CROSS JOIN repurchase_horizons h CROSS JOIN populations p
), classified AS (
    SELECT g.*, m.user_id, o.repeated, o.total_positive_purchase_value, o.repeat_positive_purchase_value,
        CASE WHEN g.population = 'horizon_mature' THEN o.has_complete_window
            WHEN g.population = 'common_horizon' THEN o.has_complete_comparison_window
            ELSE o.has_complete_comparison_window AND NOT o.has_overlapping_purchase_episodes
        END AS eligible
    FROM grid g LEFT JOIN cohort_memberships m USING (cohort_id)
    LEFT JOIN buyer_outcomes o ON o.user_id = m.user_id AND o.horizon_days = g.horizon_days
), counts AS (
    SELECT cohort_id, cohort_label, family, entry_start_utc, entry_end_exclusive_utc, horizon_days, population,
        COUNT(user_id) AS cohort_users, COUNT(user_id) FILTER (WHERE eligible) AS eligible_users,
        SUM(repeated::INTEGER) FILTER (WHERE eligible) AS repeat_users,
        SUM(total_positive_purchase_value) FILTER (WHERE eligible) AS total_positive_purchase_value,
        AVG(total_positive_purchase_value) FILTER (WHERE eligible) AS mean_value_per_user,
        MEDIAN(total_positive_purchase_value) FILTER (WHERE eligible) AS median_value_per_user,
        SUM(repeat_positive_purchase_value) FILTER (WHERE eligible) AS repeat_positive_purchase_value,
        AVG(repeat_positive_purchase_value) FILTER (WHERE eligible) AS mean_repeat_value_per_user,
        MEDIAN(repeat_positive_purchase_value) FILTER (WHERE eligible) AS median_repeat_value_per_user
    FROM classified GROUP BY ALL
)
SELECT *, repeat_users::DOUBLE / NULLIF(eligible_users, 0) AS repeat_rate
FROM counts;
