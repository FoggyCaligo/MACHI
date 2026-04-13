import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from config import DB_PATH, DATA_DIR
from tools.text_embedding import embed_text


BASE_DIR = Path(__file__).resolve().parent.parent
LEGACY_TOPIC_TABLES = ("profiles", "corrections", "episodes", "summaries")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _warn_if_stale_root_db_exists() -> None:
    root_db_path = BASE_DIR / "memory.db"

    try:
        current_db = DB_PATH.resolve()
    except FileNotFoundError:
        current_db = DB_PATH

    try:
        stale_db = root_db_path.resolve()
    except FileNotFoundError:
        stale_db = root_db_path

    if root_db_path.exists() and stale_db != current_db:
        print(
            "[MEMORY][WARN] 루트의 memory.db 파일이 남아 있습니다. "
            f"현재 사용 DB는 '{DB_PATH}' 입니다. "
            "혼동 방지를 위해 루트 memory.db는 백업 후 정리하는 것을 권장합니다.",
            flush=True,
        )


def get_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    #WAL 모드 설정
    conn.execute("PRAGMA journal_mode = WAL")   # ← 추가
    conn.execute("PRAGMA busy_timeout = 5000")  # ← 추가 (ms 단위, 5초 대기)
    return conn


@contextmanager
def connection_context():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _column_exists(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(row[1] == column_name for row in rows)


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return bool(row)


def _ensure_topics_seeded_from_legacy(conn: sqlite3.Connection, legacy_topic: str | None) -> str | None:
    normalized = " ".join((legacy_topic or "").strip().split())
    if not normalized or normalized.lower() == "general":
        return None

    row = conn.execute(
        "SELECT id FROM topics WHERE LOWER(summary) = LOWER(?) OR LOWER(name) = LOWER(?) LIMIT 1",
        (normalized, normalized),
    ).fetchone()
    if row:
        return str(row[0]).strip()

    now = utc_now()
    topic_id = str(uuid.uuid4())
    embedding = json.dumps(embed_text(normalized, kind="passage"), ensure_ascii=False)
    conn.execute(
        """
        INSERT INTO topics (
            id, name, summary, embedding_json, confidence, source, status,
            usage_count, last_used_at, created_at, updated_at, merged_into_topic_id
        ) VALUES (?, ?, ?, ?, ?, ?, 'active', 0, ?, ?, ?, NULL)
        """,
        (topic_id, normalized, normalized, embedding, 0.6, 'legacy_topic_migration', now, now, now),
    )
    return topic_id


def _migrate_profiles(conn: sqlite3.Connection) -> None:
    if not (_table_exists(conn, 'profiles') and _column_exists(conn, 'profiles', 'topic')):
        return
    rows = conn.execute("SELECT * FROM profiles").fetchall()
    conn.execute(
        """
        CREATE TABLE profiles_new (
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
        )
        """
    )
    for row in rows:
        topic_id = row['topic_id'] if _column_exists(conn, 'profiles', 'topic_id') else None
        if not topic_id:
            topic_id = _ensure_topics_seeded_from_legacy(conn, row['topic'])
        conn.execute(
            "INSERT INTO profiles_new (id, topic_id, content, confidence, source, version_no, created_at, updated_at, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (row['id'], topic_id, row['content'], row['confidence'], row['source'], row['version_no'], row['created_at'], row['updated_at'], row['status']),
        )
    conn.execute("DROP TABLE profiles")
    conn.execute("ALTER TABLE profiles_new RENAME TO profiles")


def _migrate_corrections(conn: sqlite3.Connection) -> None:
    if not (_table_exists(conn, 'corrections') and _column_exists(conn, 'corrections', 'topic')):
        return
    rows = conn.execute("SELECT * FROM corrections").fetchall()
    conn.execute(
        """
        CREATE TABLE corrections_new (
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
        )
        """
    )
    for row in rows:
        topic_id = row['topic_id'] if _column_exists(conn, 'corrections', 'topic_id') else None
        if not topic_id:
            topic_id = _ensure_topics_seeded_from_legacy(conn, row['topic'])
        conn.execute(
            "INSERT INTO corrections_new (id, topic_id, content, reason, source, confidence, supersedes_profile_id, supersedes_correction_id, applied_to_profile, created_at, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (row['id'], topic_id, row['content'], row['reason'], row['source'], row['confidence'], row['supersedes_profile_id'], row['supersedes_correction_id'], row['applied_to_profile'], row['created_at'], row['status']),
        )
    conn.execute("DROP TABLE corrections")
    conn.execute("ALTER TABLE corrections_new RENAME TO corrections")


def _migrate_episodes(conn: sqlite3.Connection) -> None:
    if not (_table_exists(conn, 'episodes') and _column_exists(conn, 'episodes', 'topic')):
        return
    rows = conn.execute("SELECT * FROM episodes").fetchall()
    conn.execute(
        """
        CREATE TABLE episodes_new (
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
        )
        """
    )
    for row in rows:
        topic_id = row['topic_id'] if _column_exists(conn, 'episodes', 'topic_id') else None
        if not topic_id:
            topic_id = _ensure_topics_seeded_from_legacy(conn, row['topic'])
        conn.execute(
            "INSERT INTO episodes_new (id, topic_id, summary, raw_ref, importance, last_referenced_at, created_at, state, pinned) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (row['id'], topic_id, row['summary'], row['raw_ref'], row['importance'], row['last_referenced_at'], row['created_at'], row['state'], row['pinned']),
        )
    conn.execute("DROP TABLE episodes")
    conn.execute("ALTER TABLE episodes_new RENAME TO episodes")


def _migrate_summaries(conn: sqlite3.Connection) -> None:
    if not (_table_exists(conn, 'summaries') and _column_exists(conn, 'summaries', 'topic')):
        return
    rows = conn.execute("SELECT * FROM summaries").fetchall()
    conn.execute(
        """
        CREATE TABLE summaries_new (
            id TEXT PRIMARY KEY,
            topic_id TEXT,
            content TEXT NOT NULL,
            source_episode_ids TEXT,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (topic_id) REFERENCES topics(id)
        )
        """
    )
    for row in rows:
        topic_id = row['topic_id'] if _column_exists(conn, 'summaries', 'topic_id') else None
        if not topic_id:
            topic_id = _ensure_topics_seeded_from_legacy(conn, row['topic'])
        conn.execute(
            "INSERT INTO summaries_new (id, topic_id, content, source_episode_ids, updated_at) VALUES (?, ?, ?, ?, ?)",
            (row['id'], topic_id, row['content'], row['source_episode_ids'], row['updated_at']),
        )
    conn.execute("DROP TABLE summaries")
    conn.execute("ALTER TABLE summaries_new RENAME TO summaries")


def _migrate_legacy_topic_tables(conn: sqlite3.Connection) -> None:
    if not any(_table_exists(conn, table) and _column_exists(conn, table, 'topic') for table in LEGACY_TOPIC_TABLES):
        return

    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        _migrate_profiles(conn)
        _migrate_corrections(conn)
        _migrate_episodes(conn)
        _migrate_summaries(conn)
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def initialize_database() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _warn_if_stale_root_db_exists()

    schema_path = BASE_DIR / "memory" / "schema.sql"
    schema = schema_path.read_text(encoding="utf-8")

    with connection_context() as conn:
        conn.executescript(schema)
        _migrate_legacy_topic_tables(conn)
        conn.executescript(schema)


def _ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, column_def: str) -> None:
    if _column_exists(conn, table_name, column_name):
        return
    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}")
