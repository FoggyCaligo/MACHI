-- MK5 schema draft (SQLite)
-- Philosophy:
-- 1) Everything enters through chat events/messages.
-- 2) The durable memory core is a graph: nodes + edges.
-- 3) graph_events keep the history of why graph changes happened.
-- 4) node_pointers represent reuse/reference instead of blind duplication.
-- 5) Structures are preserved by default, but repeated contradiction pressure
--    can lower trust until revision/replacement becomes valid.

PRAGMA foreign_keys = ON;

BEGIN TRANSACTION;

-- ---------------------------------------------------------------------------
-- Raw chat stream: unified entry point for user messages, assistant replies,
-- attached file references, and future tool/system events.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_uid TEXT NOT NULL UNIQUE,
    session_id TEXT NOT NULL,
    turn_index INTEGER NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('system', 'user', 'assistant', 'tool')),
    content TEXT NOT NULL,
    content_hash TEXT,
    attached_files_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_session_turn
    ON chat_messages(session_id, turn_index);
CREATE INDEX IF NOT EXISTS idx_chat_messages_content_hash
    ON chat_messages(content_hash);

-- ---------------------------------------------------------------------------
-- Durable graph nodes.
-- address_hash = direct address-like identifier derived from the segmented input.
-- trust_score/stability_score are persistent properties of the node itself.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_uid TEXT NOT NULL UNIQUE,
    address_hash TEXT NOT NULL UNIQUE,
    node_kind TEXT NOT NULL,
    raw_value TEXT NOT NULL,
    normalized_value TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    trust_score REAL NOT NULL DEFAULT 1.0,
    stability_score REAL NOT NULL DEFAULT 0.5,
    revision_state TEXT NOT NULL DEFAULT 'stable'
        CHECK (revision_state IN ('stable', 'under_review', 'deprecated', 'replaced')),
    created_from_event_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    FOREIGN KEY (created_from_event_id) REFERENCES graph_events(id)
);

CREATE INDEX IF NOT EXISTS idx_nodes_kind
    ON nodes(node_kind);
CREATE INDEX IF NOT EXISTS idx_nodes_normalized_value
    ON nodes(normalized_value);
CREATE INDEX IF NOT EXISTS idx_nodes_active_kind
    ON nodes(is_active, node_kind);

-- ---------------------------------------------------------------------------
-- Durable graph edges.
-- One row = one relation from source -> target.
-- trust_score + contradiction_pressure together support the “preserve by default,
-- revise when repeated conflicts accumulate” rule.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    edge_uid TEXT NOT NULL UNIQUE,
    source_node_id INTEGER NOT NULL,
    target_node_id INTEGER NOT NULL,
    edge_type TEXT NOT NULL,
    relation_detail_json TEXT NOT NULL DEFAULT '{}',
    edge_weight REAL NOT NULL DEFAULT 1.0,
    trust_score REAL NOT NULL DEFAULT 1.0,
    support_count INTEGER NOT NULL DEFAULT 0,
    conflict_count INTEGER NOT NULL DEFAULT 0,
    contradiction_pressure REAL NOT NULL DEFAULT 0.0,
    revision_candidate_flag INTEGER NOT NULL DEFAULT 0 CHECK (revision_candidate_flag IN (0, 1)),
    created_from_event_id INTEGER,
    last_supported_at TEXT,
    last_conflicted_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    FOREIGN KEY (source_node_id) REFERENCES nodes(id) ON DELETE CASCADE,
    FOREIGN KEY (target_node_id) REFERENCES nodes(id) ON DELETE CASCADE,
    FOREIGN KEY (created_from_event_id) REFERENCES graph_events(id),
    CHECK (source_node_id <> target_node_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_edges_active_relation
    ON edges(source_node_id, target_node_id, edge_type, is_active);
CREATE INDEX IF NOT EXISTS idx_edges_source
    ON edges(source_node_id);
CREATE INDEX IF NOT EXISTS idx_edges_target
    ON edges(target_node_id);
CREATE INDEX IF NOT EXISTS idx_edges_type
    ON edges(edge_type);
CREATE INDEX IF NOT EXISTS idx_edges_revision_candidate
    ON edges(revision_candidate_flag, contradiction_pressure DESC);

-- ---------------------------------------------------------------------------
-- Graph events: why/how the graph changed.
-- This is crucial for debugging, replay, trust updates, and future revisions.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS graph_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_uid TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL CHECK (
        event_type IN (
            'message_ingested',
            'node_created',
            'node_merged',
            'edge_created',
            'edge_supported',
            'edge_conflicted',
            'pointer_created',
            'structure_revised',
            'structure_replaced',
            'trust_lowered'
        )
    ),
    message_id INTEGER,
    trigger_node_id INTEGER,
    trigger_edge_id INTEGER,
    input_text TEXT,
    parsed_input_json TEXT NOT NULL DEFAULT '{}',
    effect_json TEXT NOT NULL DEFAULT '{}',
    note TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (message_id) REFERENCES chat_messages(id) ON DELETE SET NULL,
    FOREIGN KEY (trigger_node_id) REFERENCES nodes(id) ON DELETE SET NULL,
    FOREIGN KEY (trigger_edge_id) REFERENCES edges(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_graph_events_message
    ON graph_events(message_id);
CREATE INDEX IF NOT EXISTS idx_graph_events_type
    ON graph_events(event_type);
CREATE INDEX IF NOT EXISTS idx_graph_events_created_at
    ON graph_events(created_at);

-- ---------------------------------------------------------------------------
-- Pointer table: instead of duplicating already-known pieces, one node can point
-- to another node as exact reuse / partial reuse / parent reference / alias.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS node_pointers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pointer_uid TEXT NOT NULL UNIQUE,
    owner_node_id INTEGER NOT NULL,
    referenced_node_id INTEGER NOT NULL,
    pointer_type TEXT NOT NULL CHECK (
        pointer_type IN ('exact_reuse', 'partial_reuse', 'parent_reference', 'alias', 'support_reference')
    ),
    pointer_slot TEXT,
    detail_json TEXT NOT NULL DEFAULT '{}',
    created_from_event_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    FOREIGN KEY (owner_node_id) REFERENCES nodes(id) ON DELETE CASCADE,
    FOREIGN KEY (referenced_node_id) REFERENCES nodes(id) ON DELETE CASCADE,
    FOREIGN KEY (created_from_event_id) REFERENCES graph_events(id),
    CHECK (owner_node_id <> referenced_node_id)
);

CREATE INDEX IF NOT EXISTS idx_node_pointers_owner
    ON node_pointers(owner_node_id);
CREATE INDEX IF NOT EXISTS idx_node_pointers_referenced
    ON node_pointers(referenced_node_id);
CREATE INDEX IF NOT EXISTS idx_node_pointers_type
    ON node_pointers(pointer_type);

-- ---------------------------------------------------------------------------
-- Optional helper view: active outgoing relations with both endpoint values.
-- Useful during debugging and local inspection.
-- ---------------------------------------------------------------------------
CREATE VIEW IF NOT EXISTS active_edge_view AS
SELECT
    e.id AS edge_id,
    e.edge_uid,
    e.edge_type,
    e.edge_weight,
    e.trust_score AS edge_trust_score,
    e.support_count,
    e.conflict_count,
    e.contradiction_pressure,
    s.id AS source_node_id,
    s.address_hash AS source_address_hash,
    s.node_kind AS source_node_kind,
    s.normalized_value AS source_value,
    t.id AS target_node_id,
    t.address_hash AS target_address_hash,
    t.node_kind AS target_node_kind,
    t.normalized_value AS target_value,
    e.updated_at
FROM edges e
JOIN nodes s ON e.source_node_id = s.id
JOIN nodes t ON e.target_node_id = t.id
WHERE e.is_active = 1 AND s.is_active = 1 AND t.is_active = 1;

-- ---------------------------------------------------------------------------
-- Triggers for updated_at maintenance.
-- ---------------------------------------------------------------------------
CREATE TRIGGER IF NOT EXISTS trg_nodes_updated_at
AFTER UPDATE ON nodes
FOR EACH ROW
BEGIN
    UPDATE nodes SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS trg_edges_updated_at
AFTER UPDATE ON edges
FOR EACH ROW
BEGIN
    UPDATE edges SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

COMMIT;
