-- Retain purchase records and positive value. Grain: one source event. Key: (source_file, source_row_number).
CREATE OR REPLACE VIEW purchase_events AS
SELECT *, CASE WHEN price > 0 THEN price ELSE 0 END AS positive_purchase_value
FROM episode_events
WHERE event_type = 'purchase';
