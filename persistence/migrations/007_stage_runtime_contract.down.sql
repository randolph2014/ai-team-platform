ALTER TABLE stage_run DROP COLUMN IF EXISTS loopback_to;
ALTER TABLE stage_run DROP COLUMN IF EXISTS human_decision;
ALTER TABLE stage_run DROP COLUMN IF EXISTS artifact_validations;
ALTER TABLE stage_run DROP COLUMN IF EXISTS stage_type;
