import sqlite3
from pathlib import Path

from config import DB_PATH, DATA_DIR, BASE_DIR


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def initialize_database() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    schema_path = BASE_DIR / "memory" / "schema.sql"
    with open(schema_path, "r", encoding="utf-8") as f:
        schema = f.read()
    conn = get_connection()
    try:
        conn.executescript(schema)
        conn.commit()
    finally:
        conn.close()
