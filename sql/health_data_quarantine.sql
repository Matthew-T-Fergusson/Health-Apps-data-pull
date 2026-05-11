-- Data quarantine for records that fail validation but should not block the
-- entire health pipeline. This is the audit landing zone for source records,
-- derived records, or manual entries that need operator/AI-agent decisioning.

CREATE TABLE IF NOT EXISTS health.data_quarantine (
  quarantine_id BIGSERIAL PRIMARY KEY,
  source_system TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT,
  metric_date DATE,
  detection_signal TEXT NOT NULL,
  severity TEXT NOT NULL DEFAULT 'warn', -- info|warn|fail|critical
  reason TEXT NOT NULL,
  recommended_action TEXT NOT NULL DEFAULT 'review', -- review|backfill|merge|skip|purge|fix_source|escalate
  status TEXT NOT NULL DEFAULT 'open', -- open|in_review|resolved|ignored|escalated
  raw_payload JSONB,
  normalized_payload JSONB,
  evidence JSONB DEFAULT '{}'::jsonb,
  resolution_notes TEXT,
  resolved_at TIMESTAMPTZ,
  resolved_by TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (severity IN ('info','warn','fail','critical')),
  CHECK (recommended_action IN ('review','backfill','merge','skip','purge','fix_source','escalate')),
  CHECK (status IN ('open','in_review','resolved','ignored','escalated'))
);

CREATE INDEX IF NOT EXISTS idx_data_quarantine_open ON health.data_quarantine(status, severity, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_data_quarantine_source_entity ON health.data_quarantine(source_system, entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_data_quarantine_metric_date ON health.data_quarantine(metric_date DESC);

CREATE OR REPLACE VIEW health.data_quarantine_open AS
SELECT
  quarantine_id,
  source_system,
  entity_type,
  entity_id,
  metric_date,
  detection_signal,
  severity,
  reason,
  recommended_action,
  status,
  evidence,
  created_at,
  updated_at
FROM health.data_quarantine
WHERE status IN ('open', 'in_review', 'escalated')
ORDER BY
  CASE severity WHEN 'critical' THEN 1 WHEN 'fail' THEN 2 WHEN 'warn' THEN 3 ELSE 4 END,
  created_at DESC;
