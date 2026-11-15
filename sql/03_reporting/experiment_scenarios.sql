-- Preserve prospective calculations for BI. Grain: assumed absolute uplift. Key: absolute_uplift.
CREATE OR REPLACE TABLE experiment_scenarios AS
SELECT * FROM experiment_planning_input;
