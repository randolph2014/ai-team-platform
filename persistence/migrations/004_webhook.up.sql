CREATE TABLE IF NOT EXISTS webhook (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    url TEXT NOT NULL,
    secret TEXT NOT NULL,
    events JSONB NOT NULL DEFAULT '[]',
    pipeline_id UUID REFERENCES pipeline(id),
    enabled BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_webhook_enabled ON webhook(enabled);
CREATE INDEX IF NOT EXISTS idx_webhook_pipeline ON webhook(pipeline_id);
