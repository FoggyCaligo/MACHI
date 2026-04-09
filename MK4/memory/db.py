import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from config import DB_PATH, DATA_DIR


BASE_DIR = Path(__file__).resolve().parent.parent


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
    return conn


@contextmanager
def connection_context():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def initialize_database() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _warn_if_stale_root_db_exists()

    schema_path = BASE_DIR / "memory" / "schema.sql"
    schema = schema_path.read_text(encoding="utf-8")

    with connection_context() as conn:
        existing_tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}
        if "profiles" in existing_tables:
            _ensure_column(conn, "profiles", "topic_id", "TEXT")
        if "corrections" in existing_tables:
            _ensure_column(conn, "corrections", "topic_id", "TEXT")
        if "episodes" in existing_tables:
            _ensure_column(conn, "episodes", "topic_id", "TEXT")
        if "summaries" in existing_tables:
            _ensure_column(conn, "summaries", "topic_id", "TEXT")

        conn.executescript(schema)

        _ensure_column(conn, "profiles", "topic_id", "TEXT")
        _ensure_column(conn, "corrections", "topic_id", "TEXT")
        _ensure_column(conn, "episodes", "topic_id", "TEXT")
        _ensure_column(conn, "summaries", "topic_id", "TEXT")

def _column_exists(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(row[1] == column_name for row in rows)


def _ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, column_def: str) -> None:
    if _column_exists(conn, table_name, column_name):
        return
    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}")
