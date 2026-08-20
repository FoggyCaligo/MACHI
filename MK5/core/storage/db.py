"""SQLite connection and schema setup."""
from __future__ import annotations

import sqlite3
from pathlib import Path


_DDL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS words (
    word_id       TEXT PRIMARY KEY,
    surface_form  TEXT NOT NULL,
    address_hash  TEXT NOT NULL REFERENCES nodes(address_hash),
    language      TEXT,
    created_at    TEXT NOT NULL
);

DROP INDEX IF EXISTS idx_words_surface;

CREATE INDEX IF NOT EXISTS idx_words_surface
    ON words(surface_form);

CREATE UNIQUE INDEX IF NOT EXISTS idx_words_surface_address
    ON words(surface_form, address_hash);

CREATE INDEX IF NOT EXISTS idx_words_address_hash
    ON words(address_hash);

CREATE TABLE IF NOT EXISTS nodes (
    address_hash       TEXT PRIMARY KEY,
    labels             TEXT NOT NULL,
    is_abstract        INTEGER NOT NULL DEFAULT 0,
    node_kind          TEXT NOT NULL,
    embedding          BLOB,
    trust_score        REAL NOT NULL DEFAULT 0.5,
    stability_score    REAL NOT NULL DEFAULT 0.5,
    is_active          INTEGER NOT NULL DEFAULT 1,
    formation_source   TEXT NOT NULL,
    payload            TEXT NOT NULL DEFAULT '{}',
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_nodes_is_active
    ON nodes(is_active);

CREATE INDEX IF NOT EXISTS idx_nodes_trust
    ON nodes(trust_score);

CREATE TABLE IF NOT EXISTS edges (
    edge_id                  TEXT PRIMARY KEY,
    source_hash              TEXT NOT NULL REFERENCES nodes(address_hash),
    target_hash              TEXT NOT NULL REFERENCES nodes(address_hash),
    edge_family              TEXT NOT NULL,
    connect_type             TEXT NOT NULL,
    proposed_connect_type    TEXT,
    proposal_reason          TEXT,
    translation_confidence   REAL,
    provenance_source        TEXT NOT NULL,
    support_count            INTEGER NOT NULL DEFAULT 0,
    conflict_count           INTEGER NOT NULL DEFAULT 0,
    contradiction_pressure   REAL NOT NULL DEFAULT 0.0,
    trust_score              REAL NOT NULL DEFAULT 0.5,
    edge_weight              REAL NOT NULL DEFAULT 1.0,
    is_active                INTEGER NOT NULL DEFAULT 1,
    is_temporary             INTEGER NOT NULL DEFAULT 0,
    payload                  TEXT NOT NULL DEFAULT '{}',
    created_at               TEXT NOT NULL,
    updated_at               TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_edges_source
    ON edges(source_hash, is_active);

CREATE INDEX IF NOT EXISTS idx_edges_target
    ON edges(target_hash, is_active);

CREATE INDEX IF NOT EXISTS idx_edges_connect_type
    ON edges(connect_type);
"""


def open_db(db_path: str) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_DDL)
    conn.commit()
    return conn


def close_db(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.commit()
    finally:
        conn.close()
