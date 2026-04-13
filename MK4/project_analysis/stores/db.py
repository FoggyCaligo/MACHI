import sqlite3

import sqlite_vec

from config import DATA_DIR, DB_PATH


def get_conn() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _get_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row["name"] for row in rows}


def _ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, definition: str) -> None:
    existing = _get_columns(conn, table_name)
    if column_name not in existing:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def _get_vec_dimension(conn: sqlite3.Connection) -> int | None:
    """기존 vec_project_chunks 테이블의 벡터 차원 수를 읽어온다."""
    try:
        row = conn.execute(
            "SELECT vector_extract(embedding) FROM vec_project_chunks LIMIT 1"
        ).fetchone()
        if row and row[0]:
            import json
            vals = json.loads(row[0])
            return len(vals)
    except Exception:
        pass
    return None


def _ensure_vec_table(conn: sqlite3.Connection) -> None:
    """
    vec_project_chunks 가상 테이블을 생성한다.
    - 이미 존재하면 건드리지 않는다.
    - 차원 수는 multilingual-e5-small 기준 384.
    """
    existing = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='vec_project_chunks'"
    ).fetchone()
    if existing:
        return

    conn.execute(
        """
        CREATE VIRTUAL TABLE vec_project_chunks
        USING vec0(
            chunk_id TEXT PRIMARY KEY,
            embedding float[384]
        )
        """
    )


def init_project_tables() -> None:
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                zip_path TEXT,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS project_files (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                path TEXT NOT NULL,
                ext TEXT,
                size_bytes INTEGER,
                content TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(id)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS project_chunks (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                file_id TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                start_line INTEGER,
                end_line INTEGER,
                content TEXT NOT NULL,
                summary TEXT,
                embedding_json TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(id),
                FOREIGN KEY (file_id) REFERENCES project_files(id)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS project_reviews (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(id)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS project_profile_evidence (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                source_file_path TEXT NOT NULL,
                evidence_type TEXT NOT NULL,
                evidence_text TEXT NOT NULL,
                confidence REAL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(id)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS uploaded_profile_sources (
                id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                content TEXT NOT NULL,
                user_request TEXT,
                created_at TEXT NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS uploaded_profile_evidence (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                source_file_path TEXT NOT NULL,
                evidence_type TEXT NOT NULL,
                evidence_text TEXT NOT NULL,
                confidence REAL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (source_id) REFERENCES uploaded_profile_sources(id)
            )
            """
        )

        _ensure_column(conn, "project_profile_evidence", "topic", "TEXT")
        _ensure_column(conn, "project_profile_evidence", "topic_id", "TEXT")
        _ensure_column(conn, "project_profile_evidence", "candidate_content", "TEXT")
        _ensure_column(conn, "project_profile_evidence", "source_strength", "TEXT")
        _ensure_column(conn, "project_profile_evidence", "applied_to_memory", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "project_profile_evidence", "linked_profile_id", "TEXT")
        _ensure_column(conn, "project_profile_evidence", "linked_correction_id", "TEXT")
        _ensure_column(conn, "project_profile_evidence", "direct_confirm", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "project_profile_evidence", "memory_tier", "TEXT")

        _ensure_column(conn, "uploaded_profile_evidence", "topic", "TEXT")
        _ensure_column(conn, "uploaded_profile_evidence", "topic_id", "TEXT")
        _ensure_column(conn, "uploaded_profile_evidence", "candidate_content", "TEXT")
        _ensure_column(conn, "uploaded_profile_evidence", "source_strength", "TEXT")
        _ensure_column(conn, "uploaded_profile_evidence", "applied_to_memory", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "uploaded_profile_evidence", "linked_profile_id", "TEXT")
        _ensure_column(conn, "uploaded_profile_evidence", "linked_correction_id", "TEXT")
        _ensure_column(conn, "uploaded_profile_evidence", "direct_confirm", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "uploaded_profile_evidence", "memory_tier", "TEXT")

        _ensure_column(conn, "project_chunks", "embedding_json", "TEXT")

        # sqlite-vec 가상 테이블
        _ensure_vec_table(conn)

        conn.commit()