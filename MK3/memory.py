from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

from config import settings


def ensure_data_dir() -> None:
    os.makedirs(settings.data_dir, exist_ok=True)


def init_db() -> None:
    ensure_data_dir()
    with sqlite3.connect(settings.sqlite_path) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def save_message(role: str, content: str) -> None:
    with sqlite3.connect(settings.sqlite_path) as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO messages (role, content, created_at) VALUES (?, ?, ?)",
            (role, content, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()


def get_recent_messages(limit: int | None = None) -> list[dict[str, str]]:
    limit = limit or settings.recent_message_limit
    with sqlite3.connect(settings.sqlite_path) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT role, content FROM messages ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = cur.fetchall()
    rows.reverse()
    return [{"role": role, "content": content} for role, content in rows]


def load_profile() -> dict[str, Any]:
    ensure_data_dir()
    if not os.path.exists(settings.profile_path):
        profile = {
            "language": "ko",
            "name": "",
            "preferences": [
                "구조 -> 메커니즘 -> 관계 -> 적용 순서 선호",
                "팩트체크 및 논리 검증 우선",
                "모르면 모른다고 말하기",
                "근거가 부족하면 추정임을 명시하기",
            ],
            "long_term_notes": [],
        }
        with open(settings.profile_path, "w", encoding="utf-8") as f:
            json.dump(profile, f, ensure_ascii=False, indent=2)
        return profile

    with open(settings.profile_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_profile(profile: dict[str, Any]) -> None:
    ensure_data_dir()
    with open(settings.profile_path, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)


def update_profile_from_user_text(user_text: str) -> None:
    if not settings.enable_memory:
        return

    profile = load_profile()

    if "앞으로 한국어로" in user_text or "한국어로 답" in user_text:
        profile["language"] = "ko"

    rules = {
        "구조적으로 설명": "구조적 설명 필요",
        "논리 검증": "논리 검증 선호",
        "근거": "근거와 출처 중시",
        "직설": "완곡함보다 정확성 선호",
    }
    for k, v in rules.items():
        if k in user_text and v not in profile["preferences"]:
            profile["preferences"].append(v)

    save_profile(profile)


def build_memory_context() -> str:
    profile = load_profile()
    lines = ["[사용자 프로필]"]
    lines.append(f"- 언어: {profile.get('language', 'ko')}")
    if profile.get("name"):
        lines.append(f"- 이름: {profile['name']}")
    for pref in profile.get("preferences", []):
        lines.append(f"- 선호: {pref}")
    for note in profile.get("long_term_notes", []):
        lines.append(f"- 메모: {note}")
    return "\n".join(lines)
