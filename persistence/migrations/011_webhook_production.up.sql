CREATE TABLE IF NOT EXISTS webhook_delivery (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    webhook_id UUID NOT NULL REFERENCES webhook(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    request_url TEXT,
    request_headers JSONB DEFAULT '{}',
    request_body JSONB DEFAULT '{}',
    response_status INTEGER,
    response_body TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_attempt_at TIMESTAMPTZ,
    next_retry_at TIMESTAMPTZ,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_webhook_delivery_webhook ON webhook_delivery(webhook_id);
CREATE INDEX IF NOT EXISTS idx_webhook_delivery_status ON webhook_delivery(status);
CREATE INDEX IF NOT EXISTS idx_webhook_delivery_next_retry ON webhook_delivery(next_retry_at) WHERE status IN ('failed', 'pending');

CREATE INDEX IF NOT EXISTS idx_cost_tracking_model ON cost_tracking(model);
CREATE INDEX IF NOT EXISTS idx_cost_tracking_created_at ON cost_tracking(created_at);
