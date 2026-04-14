from __future__ import annotations

import sqlite3
from pathlib import Path

from storage.db import SQLiteDatabase
from storage.sqlite.chat_message_repository import SqliteChatMessageRepository
from storage.sqlite.edge_repository import SqliteEdgeRepository
from storage.sqlite.graph_event_repository import SqliteGraphEventRepository
from storage.sqlite.node_pointer_repository import SqliteNodePointerRepository
from storage.sqlite.node_repository import SqliteNodeRepository
from storage.sqlite.pattern_repository import SqlitePatternRepository
from storage.unit_of_work import UnitOfWork


class SqliteUnitOfWork(UnitOfWork):
    def __init__(self, db_path: str | Path, *, schema_path: str | Path | None = None, initialize_schema: bool = False) -> None:
        self.database = SQLiteDatabase(db_path, schema_path=schema_path)
        self._initialize_schema = initialize_schema
        self.connection: sqlite3.Connection | None = None

    def __enter__(self) -> "SqliteUnitOfWork":
        if self._initialize_schema:
            self.database.initialize_schema()
        self.connection = self.database.connect()
        self.chat_messages = SqliteChatMessageRepository(self.connection)
        self.nodes = SqliteNodeRepository(self.connection)
        self.edges = SqliteEdgeRepository(self.connection)
        self.graph_events = SqliteGraphEventRepository(self.connection)
        self.node_pointers = SqliteNodePointerRepository(self.connection)
        self.patterns = SqlitePatternRepository(self.connection)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.connection is None:
            return
        try:
            if exc_type is None:
                self.connection.commit()
            else:
                self.connection.rollback()
        finally:
            self.connection.close()
            self.connection = None

    def commit(self) -> None:
        if self.connection is None:
            raise RuntimeError("UnitOfWork is not active")
        self.connection.commit()

    def rollback(self) -> None:
        if self.connection is None:
            raise RuntimeError("UnitOfWork is not active")
        self.connection.rollback()
