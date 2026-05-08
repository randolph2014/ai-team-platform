ALTER TABLE pipeline_run DROP CONSTRAINT IF EXISTS pipeline_run_status_check;

UPDATE pipeline_run SET status = 'pending' WHERE status = 'queued';
UPDATE pipeline_run SET status = 'waiting' WHERE status = 'paused';
UPDATE pipeline_run SET status = 'running' WHERE status = 'resuming';
UPDATE pipeline_run SET status = 'failed' WHERE status = 'blocked';
UPDATE pipeline_run SET status = 'failed' WHERE status = 'archived';

ALTER TABLE pipeline_run ALTER COLUMN status SET DEFAULT 'pending';
ALTER TABLE pipeline_run ADD CONSTRAINT pipeline_run_status_check
    CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled', 'waiting'));
