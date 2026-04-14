from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from typing import Any


def dumps_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def loads_json(value: str | None, *, default: Any) -> Any:
    if value in (None, ""):
        return default
    return json.loads(value)


def as_bool(value: Any) -> bool:
    return bool(int(value)) if isinstance(value, (int, bool)) else bool(value)


def placeholders(values: Sequence[object]) -> str:
    if not values:
        raise ValueError("placeholders() requires at least one value")
    return ",".join("?" for _ in values)


def fetch_all(connection: sqlite3.Connection, sql: str, params: Sequence[object] = ()) -> list[sqlite3.Row]:
    cursor = connection.execute(sql, tuple(params))
    return list(cursor.fetchall())


def fetch_one(connection: sqlite3.Connection, sql: str, params: Sequence[object] = ()) -> sqlite3.Row | None:
    cursor = connection.execute(sql, tuple(params))
    return cursor.fetchone()
