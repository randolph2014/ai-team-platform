ALTER TABLE pipeline_run DROP CONSTRAINT IF EXISTS pipeline_run_status_check;

UPDATE pipeline_run SET status = 'queued' WHERE status = 'pending';
UPDATE pipeline_run SET status = 'paused' WHERE status = 'waiting';

ALTER TABLE pipeline_run ALTER COLUMN status SET DEFAULT 'queued';
ALTER TABLE pipeline_run ADD CONSTRAINT pipeline_run_status_check
    CHECK (status IN ('queued', 'running', 'paused', 'resuming', 'completed', 'failed', 'cancelled', 'archived', 'blocked'));
