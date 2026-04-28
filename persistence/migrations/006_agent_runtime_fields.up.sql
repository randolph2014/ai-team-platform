ALTER TABLE agent_run ADD COLUMN IF NOT EXISTS runtime_id TEXT;
ALTER TABLE agent_run ADD COLUMN IF NOT EXISTS runtime_cli TEXT;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'agent_run'
          AND column_name = 'provider'
    ) THEN
        EXECUTE
            'UPDATE agent_run
             SET runtime_id = COALESCE(runtime_id, provider),
                 runtime_cli = COALESCE(runtime_cli, provider)
             WHERE runtime_id IS NULL';
    ELSE
        UPDATE agent_run
        SET runtime_id = COALESCE(runtime_id, runtime_cli, 'unknown')
        WHERE runtime_id IS NULL;
    END IF;
END $$;

ALTER TABLE agent_run ALTER COLUMN runtime_id SET NOT NULL;
ALTER TABLE agent_run DROP COLUMN IF EXISTS provider;
