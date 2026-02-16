-- Migration 001: Bias detection and optimization tables

-- Bias detection flags
CREATE TABLE IF NOT EXISTS bias_flags (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    knowledge_id    INTEGER NOT NULL REFERENCES knowledge_entries(id) ON DELETE CASCADE,
    bias_type       TEXT NOT NULL
        CHECK (bias_type IN ('brand_promotion', 'affiliate', 'sponsored', 'product_placement', 'unsubstantiated_claim')),
    bias_severity   TEXT NOT NULL DEFAULT 'medium'
        CHECK (bias_severity IN ('low', 'medium', 'high')),
    brand_names     TEXT,
    bias_notes      TEXT NOT NULL,
    detected_by     TEXT NOT NULL DEFAULT 'bias_agent',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(knowledge_id, bias_type)
);

CREATE INDEX IF NOT EXISTS idx_bias_flags_knowledge_id ON bias_flags(knowledge_id);
CREATE INDEX IF NOT EXISTS idx_bias_flags_bias_type ON bias_flags(bias_type);

-- Optimization queue (destructive changes awaiting approval)
CREATE TABLE IF NOT EXISTS optimization_queue (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    action_type     TEXT NOT NULL
        CHECK (action_type IN ('re_ingest', 'delete_entry', 'merge_videos',
                               'reclassify', 'merge_entries', 'normalize_tags',
                               'fill_metadata', 'rescore')),
    severity        TEXT NOT NULL DEFAULT 'suggestion'
        CHECK (severity IN ('auto', 'suggestion', 'destructive')),
    status          TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected', 'executed', 'failed')),
    target_type     TEXT NOT NULL,
    target_id       INTEGER,
    description     TEXT NOT NULL,
    details         TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at     TEXT,
    resolved_by     TEXT
);

CREATE INDEX IF NOT EXISTS idx_optqueue_status ON optimization_queue(status);
CREATE INDEX IF NOT EXISTS idx_optqueue_action ON optimization_queue(action_type);

-- Optimization log (what the optimizer has done)
CREATE TABLE IF NOT EXISTS optimization_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    queue_id        INTEGER REFERENCES optimization_queue(id),
    action_type     TEXT NOT NULL,
    description     TEXT NOT NULL,
    details         TEXT,
    executed_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
