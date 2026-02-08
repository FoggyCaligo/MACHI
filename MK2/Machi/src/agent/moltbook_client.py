# src/agent/moltbook_client.py
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Optional

import requests

API_BASE = os.getenv("MOLTBOOK_API_BASE", "https://www.moltbook.com/api/v1")  # :contentReference[oaicite:2]{index=2}
CREDS_PATH = os.getenv("MOLTBOOK_CREDS_PATH", os.path.join("runtime", "moltbook_credentials.json"))

TIMEOUTSEC = 1000

@dataclass
class MoltbookCreds:
    api_key: str
    agent_name: str
    agent_id: str

def _ensure_runtime_dir():
    d = os.path.dirname(CREDS_PATH)
    if d:
        os.makedirs(d, exist_ok=True)

def load_creds() -> Optional[MoltbookCreds]:
    if not os.path.exists(CREDS_PATH):
        return None
    with open(CREDS_PATH, "r", encoding="utf-8") as f:
        obj = json.load(f)
    if not obj.get("api_key"):
        return None
    return MoltbookCreds(
        api_key=obj["api_key"],
        agent_name=obj.get("agent_name", ""),
        agent_id=obj.get("agent_id", ""),
    )

def save_creds(api_key: str, agent_name: str, agent_id: str):
    _ensure_runtime_dir()
    with open(CREDS_PATH, "w", encoding="utf-8") as f:
        json.dump({"api_key": api_key, "agent_name": agent_name, "agent_id": agent_id}, f, ensure_ascii=False, indent=2)

def _auth_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",  # :contentReference[oaicite:3]{index=3}
        "Content-Type": "application/json",
    }

def register_agent(name: str, description: str) -> dict[str, Any]:
    # POST /agents/register (무인증) :contentReference[oaicite:4]{index=4}
    url = f"{API_BASE}/agents/register"
    r = requests.post(url, json={"name": name, "description": description}, timeout=30)
    r.raise_for_status()
    return r.json()

def get_posts(sort: str = "hot", limit: int = 5, api_key: Optional[str] = None) -> dict[str, Any]:
    # GET /posts?sort=hot|new&limit=N :contentReference[oaicite:5]{index=5}
    url = f"{API_BASE}/posts"
    params = {"sort": sort, "limit": limit}
    headers = _auth_headers(api_key) if api_key else {"Content-Type": "application/json"}
    r = requests.get(url, params=params, headers=headers, timeout=TIMEOUTSEC)
    r.raise_for_status()
    return r.json()

def create_post(title: str, content: str, submolt: Optional[str], api_key: str) -> dict[str, Any]:
    # POST /posts :contentReference[oaicite:6]{index=6}
    url = f"{API_BASE}/posts"
    payload: dict[str, Any] = {"title": title, "content": content}
    if submolt:
        payload["submolt"] = submolt
    r = requests.post(url, headers=_auth_headers(api_key), json=payload, timeout=TIMEOUTSEC)
    r.raise_for_status()
    return r.json()

def reply(post_id: str, text: str, api_key: str) -> dict[str, Any]:
    # POST /posts/{id}/comments :contentReference[oaicite:7]{index=7}
    url = f"{API_BASE}/posts/{post_id}/comments"
    r = requests.post(url, headers=_auth_headers(api_key), json={"text": text}, timeout=TIMEOUTSEC)
    r.raise_for_status()
    return r.json()
