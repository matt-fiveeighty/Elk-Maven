PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ============================================================
-- CORE TABLES
-- ============================================================

CREATE TABLE IF NOT EXISTS channels (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id      TEXT NOT NULL UNIQUE,
    channel_name    TEXT NOT NULL,
    channel_url     TEXT NOT NULL,
    description     TEXT,
    subscriber_count INTEGER,
    video_count     INTEGER,
    thumbnail_url   TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS videos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id        TEXT NOT NULL UNIQUE,
    channel_id      INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    title           TEXT NOT NULL,
    description     TEXT,
    published_at    TEXT,
    duration_seconds INTEGER,
    view_count      INTEGER,
    like_count      INTEGER,
    thumbnail_url   TEXT,
    ingestion_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (ingestion_status IN ('pending', 'transcript_fetched', 'analyzed', 'failed', 'skipped')),
    failure_reason  TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_videos_channel_id ON videos(channel_id);
CREATE INDEX IF NOT EXISTS idx_videos_ingestion_status ON videos(ingestion_status);
CREATE INDEX IF NOT EXISTS idx_videos_published_at ON videos(published_at);

CREATE TABLE IF NOT EXISTS transcripts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id        INTEGER NOT NULL UNIQUE REFERENCES videos(id) ON DELETE CASCADE,
    language_code   TEXT NOT NULL DEFAULT 'en',
    is_generated    BOOLEAN NOT NULL DEFAULT 0,
    full_text       TEXT NOT NULL,
    snippet_data    TEXT NOT NULL,
    word_count      INTEGER NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- CATEGORIZATION TABLES
-- ============================================================

CREATE TABLE IF NOT EXISTS categories (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    slug            TEXT NOT NULL UNIQUE,
    parent_id       INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    description     TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_categories_parent_id ON categories(parent_id);
CREATE INDEX IF NOT EXISTS idx_categories_slug ON categories(slug);

CREATE TABLE IF NOT EXISTS tags (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- KNOWLEDGE TABLES
-- ============================================================

CREATE TABLE IF NOT EXISTS knowledge_entries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id        INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    entry_type      TEXT NOT NULL
        CHECK (entry_type IN ('insight', 'tip', 'concept', 'technique', 'warning', 'resource', 'quote')),
    title           TEXT NOT NULL,
    content         TEXT NOT NULL,
    source_start_time REAL,
    source_end_time REAL,
    source_quote    TEXT,
    confidence      REAL NOT NULL DEFAULT 0.8
        CHECK (confidence >= 0.0 AND confidence <= 1.0),
    chunk_index     INTEGER,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_knowledge_video_id ON knowledge_entries(video_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_entry_type ON knowledge_entries(entry_type);
CREATE INDEX IF NOT EXISTS idx_knowledge_confidence ON knowledge_entries(confidence);

CREATE TABLE IF NOT EXISTS knowledge_categories (
    knowledge_id    INTEGER NOT NULL REFERENCES knowledge_entries(id) ON DELETE CASCADE,
    category_id     INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    PRIMARY KEY (knowledge_id, category_id)
);

CREATE TABLE IF NOT EXISTS knowledge_tags (
    knowledge_id    INTEGER NOT NULL REFERENCES knowledge_entries(id) ON DELETE CASCADE,
    tag_id          INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (knowledge_id, tag_id)
);

CREATE TABLE IF NOT EXISTS video_tags (
    video_id        INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    tag_id          INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (video_id, tag_id)
);

-- ============================================================
-- PROCESSING METADATA
-- ============================================================

CREATE TABLE IF NOT EXISTS processing_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id        INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    step            TEXT NOT NULL
        CHECK (step IN ('fetch_transcript', 'analyze_chunk', 'store_knowledge')),
    chunk_index     INTEGER,
    status          TEXT NOT NULL
        CHECK (status IN ('started', 'completed', 'failed')),
    tokens_used     INTEGER,
    error_message   TEXT,
    started_at      TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_processing_log_video_id ON processing_log(video_id);

-- ============================================================
-- FULL-TEXT SEARCH (FTS5)
-- ============================================================

CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
    title,
    content,
    source_quote,
    content='knowledge_entries',
    content_rowid='id',
    tokenize='porter unicode61'
);

CREATE VIRTUAL TABLE IF NOT EXISTS transcript_fts USING fts5(
    full_text,
    content='transcripts',
    content_rowid='id',
    tokenize='porter unicode61'
);

CREATE VIRTUAL TABLE IF NOT EXISTS video_fts USING fts5(
    title,
    description,
    content='videos',
    content_rowid='id',
    tokenize='porter unicode61'
);

-- ============================================================
-- TRIGGERS: Keep FTS in sync
-- ============================================================

CREATE TRIGGER IF NOT EXISTS knowledge_ai AFTER INSERT ON knowledge_entries BEGIN
    INSERT INTO knowledge_fts(rowid, title, content, source_quote)
    VALUES (new.id, new.title, new.content, new.source_quote);
END;

CREATE TRIGGER IF NOT EXISTS knowledge_ad AFTER DELETE ON knowledge_entries BEGIN
    INSERT INTO knowledge_fts(knowledge_fts, rowid, title, content, source_quote)
    VALUES ('delete', old.id, old.title, old.content, old.source_quote);
END;

CREATE TRIGGER IF NOT EXISTS knowledge_au AFTER UPDATE ON knowledge_entries BEGIN
    INSERT INTO knowledge_fts(knowledge_fts, rowid, title, content, source_quote)
    VALUES ('delete', old.id, old.title, old.content, old.source_quote);
    INSERT INTO knowledge_fts(rowid, title, content, source_quote)
    VALUES (new.id, new.title, new.content, new.source_quote);
END;

CREATE TRIGGER IF NOT EXISTS transcript_ai AFTER INSERT ON transcripts BEGIN
    INSERT INTO transcript_fts(rowid, full_text) VALUES (new.id, new.full_text);
END;

CREATE TRIGGER IF NOT EXISTS transcript_ad AFTER DELETE ON transcripts BEGIN
    INSERT INTO transcript_fts(transcript_fts, rowid, full_text)
    VALUES ('delete', old.id, old.full_text);
END;

CREATE TRIGGER IF NOT EXISTS video_ai AFTER INSERT ON videos BEGIN
    INSERT INTO video_fts(rowid, title, description)
    VALUES (new.id, new.title, new.description);
END;

CREATE TRIGGER IF NOT EXISTS video_ad AFTER DELETE ON videos BEGIN
    INSERT INTO video_fts(video_fts, rowid, title, description)
    VALUES ('delete', old.id, old.title, old.description);
END;

CREATE TRIGGER IF NOT EXISTS video_au AFTER UPDATE ON videos BEGIN
    INSERT INTO video_fts(video_fts, rowid, title, description)
    VALUES ('delete', old.id, old.title, old.description);
    INSERT INTO video_fts(rowid, title, description)
    VALUES (new.id, new.title, new.description);
END;
