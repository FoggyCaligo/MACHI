from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler

from src.agent.memory import init_db, add_chat
from src.agent.planner import respond
from src.agent.approvals import request_approval, list_pending, resolve
from src.agent.autonomy import daily_briefing

from src.agent.moltbook_commands import parse_moltbook_command
from src.agent import moltbook_client

import re, json, os

load_dotenv("runtime/.env")

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="Jaeyong Local Agent", lifespan=lifespan)

# 자율 스케줄 (예: 매일 09:00)
sched = BackgroundScheduler()
sched.add_job(daily_briefing, "cron", hour=9, minute=0)
sched.start()

class ChatIn(BaseModel):
    text: str

class ApprovalResolveIn(BaseModel):
    approve: bool

ACTION_RE = re.compile(r"ACTION_REQUEST:\s*(\w+)\s*PAYLOAD:\s*(\{.*\})", re.S)

@app.post("/chat")
def chat(inp: ChatIn):    
    add_chat("user", inp.text)
    out = respond(inp.text)
    add_chat("assistant", out)

    cmd = parse_moltbook_command(inp.text)
    if cmd:
        if cmd["type"] == "help":
            return {"type":"reply","assistant": (
                "Moltbook 명령:\n"
                "- /moltbook status\n"
                "- /moltbook hot [N]\n"
                "- /moltbook new [N]\n"
                "- /moltbook register \"이름\" \"설명\"  (승인 필요)\n"
                "- /moltbook post \"제목\" \"내용\" [--submolt guild] (승인 필요)\n"
                "- /moltbook reply <post_id> \"댓글\" (승인 필요)\n"
            )}

        if cmd["type"] == "status":
            return {"type":"reply","assistant": f"creds={'YES' if cmd['has_creds'] else 'NO'}\n{cmd['creds']}"}

        if cmd["type"] == "read":
            creds = moltbook_client.load_creds()
            out = moltbook_client.get_posts(sort=cmd["cmd"], limit=cmd["limit"], api_key=creds.api_key if creds else None)
            return {"type":"reply","assistant": json.dumps(out, ensure_ascii=False, indent=2)}

        if cmd["type"] == "needs_approval":
            # 여기서 너의 add_approval(...) 또는 DB insert 함수를 호출해서
            # action_type/payload를 approvals 테이블에 넣으면 됨.
            approval_id = create_approval(cmd["action_type"], json.dumps(cmd["payload"], ensure_ascii=False))
            return {"type":"reply","assistant": f"승인 요청 생성됨: #{approval_id} (오른쪽 패널에서 승인/거절)"}

        if cmd["type"] == "error":
            return {"type":"reply","assistant": cmd["message"]}


    m = ACTION_RE.search(out)
    if m:
        action_type = m.group(1).strip()
        payload_raw = m.group(2).strip()
        try:
            payload = json.loads(payload_raw)
        except Exception:
            payload = {"raw": payload_raw}
        approval_id = request_approval(action_type, payload)
        return {"type": "needs_approval", "approval_id": approval_id, "assistant": out}

    return {"type": "reply", "assistant": out}

@app.get("/approvals/pending")
def approvals_pending():
    return {"pending": list_pending()}

@app.get("/", include_in_schema=False)
def home():
    return {"ok": True, "ui": "/ui"}

@app.get("/ui", include_in_schema=False)
def ui():
    return FileResponse("ui/chat.html")

@app.post("/approvals/{approval_id}")
def approvals_resolve(approval_id: int, inp: ApprovalResolveIn):
    resolve(approval_id, inp.approve)
    return {"ok": True}


@app.on_event("startup")
def startup():
    init_db()