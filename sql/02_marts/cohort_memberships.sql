-- Assign first observed purchasers. Grain: one user in a cohort. Key: (cohort_id, user_id).
CREATE OR REPLACE TABLE cohort_memberships AS
SELECT d.cohort_id, b.user_id
FROM buyer_history b JOIN cohort_definitions d
    ON b.first_purchase_utc >= d.entry_start_utc AND b.first_purchase_utc < d.entry_end_exclusive_utc;
