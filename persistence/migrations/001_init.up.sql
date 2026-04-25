CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS pipeline (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    description TEXT,
    project_path TEXT NOT NULL,
    config JSONB NOT NULL,
    version INT NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pipeline_version (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_id UUID NOT NULL REFERENCES pipeline(id) ON DELETE CASCADE,
    version INT NOT NULL,
    config JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(pipeline_id, version)
);

CREATE TABLE IF NOT EXISTS pipeline_run (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_id UUID REFERENCES pipeline(id),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled', 'waiting')),
    project_root TEXT NOT NULL,
    main_branch TEXT NOT NULL DEFAULT 'main',
    requirement TEXT,
    trigger_source TEXT NOT NULL DEFAULT 'manual'
        CHECK (trigger_source IN ('manual', 'api', 'webhook')),
    worktree_path TEXT,
    context JSONB NOT NULL DEFAULT '{}',
    error_message TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    duration_seconds FLOAT
);

CREATE TABLE IF NOT EXISTS stage_run (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_run_id UUID NOT NULL REFERENCES pipeline_run(id) ON DELETE CASCADE,
    stage_id TEXT NOT NULL,
    stage_name TEXT NOT NULL,
    iteration INT NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed', 'failed', 'skipped', 'cancelled', 'waiting')),
    is_parallel BOOLEAN NOT NULL DEFAULT false,
    loopback_from TEXT,
    error_message TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    duration_seconds FLOAT,
    output_dir TEXT,
    UNIQUE(pipeline_run_id, stage_id, iteration)
);

CREATE TABLE IF NOT EXISTS agent_run (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    stage_run_id UUID NOT NULL REFERENCES stage_run(id) ON DELETE CASCADE,
    agent_name TEXT NOT NULL,
    provider TEXT NOT NULL,
    role TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed', 'failed', 'timeout', 'cancelled')),
    output_file TEXT,
    raw_log_file TEXT,
    exit_code INT,
    error_message TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    duration_seconds FLOAT
);

CREATE TABLE IF NOT EXISTS quality_gate_run (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    stage_run_id UUID NOT NULL REFERENCES stage_run(id) ON DELETE CASCADE,
    gate_name TEXT NOT NULL,
    gate_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'passed', 'failed', 'skipped', 'warning')),
    command TEXT,
    exit_code INT,
    output TEXT,
    required BOOLEAN NOT NULL DEFAULT true,
    retry_count INT NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_pipeline_run_status ON pipeline_run(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_pipeline_run_pipeline ON pipeline_run(pipeline_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_stage_run_pipeline ON stage_run(pipeline_run_id, iteration);
CREATE INDEX IF NOT EXISTS idx_agent_run_stage ON agent_run(stage_run_id);
CREATE INDEX IF NOT EXISTS idx_quality_gate_stage ON quality_gate_run(stage_run_id);
