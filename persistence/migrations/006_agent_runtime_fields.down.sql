ALTER TABLE agent_run ADD COLUMN IF NOT EXISTS provider TEXT;

DO $$
BEGIN
    IF EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'agent_run'
              AND column_name = 'runtime_id'
    ) THEN
        IF EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'agent_run'
              AND column_name = 'runtime_cli'
        ) THEN
            EXECUTE
                'UPDATE agent_run
                 SET provider = COALESCE(provider, runtime_id, runtime_cli, ''unknown'')
                 WHERE provider IS NULL';
        ELSE
            EXECUTE
                'UPDATE agent_run
                 SET provider = COALESCE(provider, runtime_id, ''unknown'')
                 WHERE provider IS NULL';
        END IF;
    ELSE
        UPDATE agent_run
        SET provider = COALESCE(provider, 'unknown')
        WHERE provider IS NULL;
    END IF;
END $$;

ALTER TABLE agent_run ALTER COLUMN provider SET NOT NULL;
ALTER TABLE agent_run DROP COLUMN IF EXISTS runtime_id;
ALTER TABLE agent_run DROP COLUMN IF EXISTS runtime_cli;
