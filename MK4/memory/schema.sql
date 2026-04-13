PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS topics (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    summary TEXT NOT NULL,
    embedding_json TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.0,
    source TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'merged', 'archived', 'dropped')),
    usage_count INTEGER NOT NULL DEFAULT 0,
    last_used_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    merged_into_topic_id TEXT,
    FOREIGN KEY (merged_into_topic_id) REFERENCES topics(id)
);

CREATE INDEX IF NOT EXISTS idx_topics_status_updated ON topics(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_topics_status_last_used ON topics(status, last_used_at DESC);
CREATE INDEX IF NOT EXISTS idx_topics_summary_name ON topics(summary, name);

CREATE TABLE IF NOT EXISTS profiles (
    id TEXT PRIMARY KEY,
    topic_id TEXT,
    content TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    source TEXT NOT NULL,
    version_no INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'superseded')),
    FOREIGN KEY (topic_id) REFERENCES topics(id)
);

CREATE INDEX IF NOT EXISTS idx_profiles_topic_id_status ON profiles(topic_id, status);
CREATE INDEX IF NOT EXISTS idx_profiles_updated_at ON profiles(updated_at DESC);

CREATE TABLE IF NOT EXISTS corrections (
    id TEXT PRIMARY KEY,
    topic_id TEXT,
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
    FOREIGN KEY (supersedes_correction_id) REFERENCES corrections(id),
    FOREIGN KEY (topic_id) REFERENCES topics(id)
);

CREATE INDEX IF NOT EXISTS idx_corrections_topic_id_status ON corrections(topic_id, status);
CREATE INDEX IF NOT EXISTS idx_corrections_created_at ON corrections(created_at DESC);

CREATE TABLE IF NOT EXISTS episodes (
    id TEXT PRIMARY KEY,
    topic_id TEXT,
    summary TEXT NOT NULL,
    raw_ref TEXT,
    importance REAL NOT NULL DEFAULT 0.5,
    last_referenced_at TEXT,
    created_at TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('active', 'compressed', 'dropped')),
    pinned INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (topic_id) REFERENCES topics(id)
);

CREATE INDEX IF NOT EXISTS idx_episodes_topic_id_state ON episodes(topic_id, state);
CREATE INDEX IF NOT EXISTS idx_episodes_last_referenced ON episodes(last_referenced_at DESC);
CREATE INDEX IF NOT EXISTS idx_episodes_created_at ON episodes(created_at DESC);

CREATE TABLE IF NOT EXISTS summaries (
    id TEXT PRIMARY KEY,
    topic_id TEXT,
    content TEXT NOT NULL,
    source_episode_ids TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (topic_id) REFERENCES topics(id)
);

CREATE INDEX IF NOT EXISTS idx_summaries_topic_id ON summaries(topic_id);
CREATE INDEX IF NOT EXISTS idx_summaries_updated_at ON summaries(updated_at DESC);

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


CREATE TABLE IF NOT EXISTS chat_profile_evidence (
    id TEXT PRIMARY KEY,
    source_message_id TEXT,
    response_message_id TEXT,
    topic TEXT,
    topic_id TEXT,
    candidate_content TEXT,
    source_strength TEXT,
    evidence_text TEXT NOT NULL,
    confidence REAL,
    direct_confirm INTEGER NOT NULL DEFAULT 0,
    applied_to_memory INTEGER NOT NULL DEFAULT 0,
    linked_profile_id TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (source_message_id) REFERENCES raw_messages(id),
    FOREIGN KEY (response_message_id) REFERENCES raw_messages(id),
    FOREIGN KEY (topic_id) REFERENCES topics(id),
    FOREIGN KEY (linked_profile_id) REFERENCES profiles(id)
);

CREATE INDEX IF NOT EXISTS idx_chat_profile_evidence_created_at ON chat_profile_evidence(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_profile_evidence_topic_id ON chat_profile_evidence(topic_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_profile_evidence_candidate ON chat_profile_evidence(candidate_content, created_at DESC);

CREATE TABLE IF NOT EXISTS raw_messages (
    id TEXT PRIMARY KEY,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    episode_id TEXT,
    FOREIGN KEY (episode_id) REFERENCES episodes(id)
);

CREATE INDEX IF NOT EXISTS idx_raw_messages_created_at ON raw_messages(created_at DESC);
