PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS profiles (
    id TEXT PRIMARY KEY,
    topic TEXT NOT NULL,
    content TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    source TEXT NOT NULL,
    version_no INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'superseded'))
);

CREATE INDEX IF NOT EXISTS idx_profiles_topic_status ON profiles(topic, status);

CREATE TABLE IF NOT EXISTS corrections (
    id TEXT PRIMARY KEY,
    topic TEXT NOT NULL,
    content TEXT NOT NULL,
    reason TEXT,
    source TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    supersedes_profile_id TEXT,
    supersedes_correction_id TEXT,
    applied_to_profile INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'applied', 'removed')),
    FOREIGN KEY (supersedes_profile_id) REFERENCES profiles(id),
    FOREIGN KEY (supersedes_correction_id) REFERENCES corrections(id)
);

CREATE INDEX IF NOT EXISTS idx_corrections_topic_status ON corrections(topic, status);
CREATE INDEX IF NOT EXISTS idx_corrections_created_at ON corrections(created_at);

CREATE TABLE IF NOT EXISTS episodes (
    id TEXT PRIMARY KEY,
    topic TEXT,
    summary TEXT NOT NULL,
    raw_ref TEXT,
    importance REAL NOT NULL DEFAULT 0.5,
    last_referenced_at TEXT,
    created_at TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('active', 'compressed', 'dropped')),
    pinned INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_episodes_topic_state ON episodes(topic, state);
CREATE INDEX IF NOT EXISTS idx_episodes_last_referenced ON episodes(last_referenced_at);

CREATE TABLE IF NOT EXISTS summaries (
    id TEXT PRIMARY KEY,
    topic TEXT NOT NULL,
    content TEXT NOT NULL,
    source_episode_ids TEXT,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_summaries_topic ON summaries(topic);

CREATE TABLE IF NOT EXISTS states (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    source TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_links (
    id TEXT PRIMARY KEY,
    from_type TEXT NOT NULL,
    from_id TEXT NOT NULL,
    to_type TEXT NOT NULL,
    to_id TEXT NOT NULL,
    relation TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_links_from ON memory_links(from_type, from_id);
CREATE INDEX IF NOT EXISTS idx_memory_links_to ON memory_links(to_type, to_id);

CREATE TABLE IF NOT EXISTS raw_messages (
    id TEXT PRIMARY KEY,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    episode_id TEXT,
    FOREIGN KEY (episode_id) REFERENCES episodes(id)
);

CREATE INDEX IF NOT EXISTS idx_raw_messages_created_at ON raw_messages(created_at);
