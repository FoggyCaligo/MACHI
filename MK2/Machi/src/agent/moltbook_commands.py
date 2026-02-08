# src/agent/moltbook_commands.py
from __future__ import annotations

import shlex
from typing import Optional

from src.agent import moltbook_client

def parse_moltbook_command(text: str) -> Optional[dict]:
    # 예: /moltbook hot 5
    # 예: /moltbook register "AgentName" "desc..."
    # 예: /moltbook post "title" "content" --submolt guild
    if not text.strip().startswith("/moltbook"):
        return None

    args = shlex.split(text)
    if len(args) < 2:
        return {"type": "help"}

    cmd = args[1].lower()

    if cmd in ("hot", "new"):
        n = int(args[2]) if len(args) >= 3 else 5
        return {"type": "read", "cmd": cmd, "limit": n}

    if cmd == "status":
        creds = moltbook_client.load_creds()
        return {"type": "status", "has_creds": bool(creds), "creds": creds.__dict__ if creds else None}

    if cmd == "register":
        if len(args) < 4:
            return {"type": "error", "message": '사용법: /moltbook register "이름" "설명"'}
        return {"type": "needs_approval", "action_type": "MOLTBOOK_REGISTER", "payload": {"name": args[2], "description": args[3]}}

    if cmd == "post":
        if len(args) < 4:
            return {"type": "error", "message": '사용법: /moltbook post "제목" "내용" [--submolt guild]'}
        submolt = None
        if "--submolt" in args:
            i = args.index("--submolt")
            if i + 1 < len(args):
                submolt = args[i + 1]
        return {"type": "needs_approval", "action_type": "MOLTBOOK_POST", "payload": {"title": args[2], "content": args[3], "submolt": submolt}}

    if cmd == "reply":
        if len(args) < 4:
            return {"type": "error", "message": '사용법: /moltbook reply <post_id> "댓글"'}
        return {"type": "needs_approval", "action_type": "MOLTBOOK_REPLY", "payload": {"post_id": args[2], "text": args[3]}}

    return {"type": "help"}
