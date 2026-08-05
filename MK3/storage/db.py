from __future__ import annotations

import sqlite3
from pathlib import Path


class SQLiteDatabase:
    """Small bootstrap/helper around a SQLite database file."""

    def __init__(self, db_path: str | Path, *, schema_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path)
        self.schema_path = Path(schema_path) if schema_path is not None else Path(__file__).with_name("schema.sql")

    def connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.db_path))
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON;")
        return connection

    def initialize_schema(self) -> None:
        sql = self.schema_path.read_text(encoding="utf-8")
        with self.connect() as connection:
            connection.executescript(sql)
            connection.commit()
