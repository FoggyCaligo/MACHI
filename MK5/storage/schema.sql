PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_uid TEXT NOT NULL UNIQUE,
    session_id TEXT NOT NULL,
    turn_index INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    content_hash TEXT,
    attached_files_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_session_turn
    ON chat_messages(session_id, turn_index, id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_content_hash
    ON chat_messages(content_hash);

CREATE TABLE IF NOT EXISTS graph_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_uid TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    message_id INTEGER,
    trigger_node_id INTEGER,
    trigger_edge_id INTEGER,
    input_text TEXT,
    parsed_input_json TEXT NOT NULL DEFAULT '{}',
    effect_json TEXT NOT NULL DEFAULT '{}',
    note TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (message_id) REFERENCES chat_messages(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_graph_events_message ON graph_events(message_id, id);
CREATE INDEX IF NOT EXISTS idx_graph_events_type ON graph_events(event_type, id);
CREATE INDEX IF NOT EXISTS idx_graph_events_node ON graph_events(trigger_node_id, id);
CREATE INDEX IF NOT EXISTS idx_graph_events_edge ON graph_events(trigger_edge_id, id);

CREATE TABLE IF NOT EXISTS nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_uid TEXT NOT NULL UNIQUE,
    address_hash TEXT NOT NULL UNIQUE,
    node_kind TEXT NOT NULL,
    raw_value TEXT NOT NULL,
    normalized_value TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    trust_score REAL NOT NULL DEFAULT 0.5,
    stability_score REAL NOT NULL DEFAULT 0.5,
    revision_state TEXT NOT NULL DEFAULT 'stable',
    created_from_event_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_active INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (created_from_event_id) REFERENCES graph_events(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_nodes_normalized_value ON nodes(normalized_value);
CREATE INDEX IF NOT EXISTS idx_nodes_kind_active ON nodes(node_kind, is_active);
CREATE INDEX IF NOT EXISTS idx_nodes_trust ON nodes(trust_score DESC, stability_score DESC);

CREATE TABLE IF NOT EXISTS edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    edge_uid TEXT NOT NULL UNIQUE,
    source_node_id INTEGER NOT NULL,
    target_node_id INTEGER NOT NULL,
    edge_type TEXT NOT NULL,
    relation_detail_json TEXT NOT NULL DEFAULT '{}',
    edge_weight REAL NOT NULL DEFAULT 0.1,
    trust_score REAL NOT NULL DEFAULT 0.5,
    support_count INTEGER NOT NULL DEFAULT 0,
    conflict_count INTEGER NOT NULL DEFAULT 0,
    contradiction_pressure REAL NOT NULL DEFAULT 0.0,
    revision_candidate_flag INTEGER NOT NULL DEFAULT 0,
    created_from_event_id INTEGER,
    last_supported_at TEXT,
    last_conflicted_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_active INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (source_node_id) REFERENCES nodes(id) ON DELETE CASCADE,
    FOREIGN KEY (target_node_id) REFERENCES nodes(id) ON DELETE CASCADE,
    FOREIGN KEY (created_from_event_id) REFERENCES graph_events(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_node_id, is_active, edge_type);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_node_id, is_active, edge_type);
CREATE INDEX IF NOT EXISTS idx_edges_pair_type ON edges(source_node_id, target_node_id, edge_type, is_active);
CREATE INDEX IF NOT EXISTS idx_edges_revision ON edges(revision_candidate_flag, contradiction_pressure DESC, id);

CREATE TABLE IF NOT EXISTS node_pointers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pointer_uid TEXT NOT NULL UNIQUE,
    owner_node_id INTEGER NOT NULL,
    referenced_node_id INTEGER NOT NULL,
    pointer_type TEXT NOT NULL,
    pointer_slot TEXT,
    detail_json TEXT NOT NULL DEFAULT '{}',
    created_from_event_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_active INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (owner_node_id) REFERENCES nodes(id) ON DELETE CASCADE,
    FOREIGN KEY (referenced_node_id) REFERENCES nodes(id) ON DELETE CASCADE,
    FOREIGN KEY (created_from_event_id) REFERENCES graph_events(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_node_pointers_owner ON node_pointers(owner_node_id, is_active);
CREATE INDEX IF NOT EXISTS idx_node_pointers_referenced ON node_pointers(referenced_node_id, is_active);
CREATE INDEX IF NOT EXISTS idx_node_pointers_dedupe ON node_pointers(owner_node_id, referenced_node_id, pointer_type, pointer_slot, is_active);
