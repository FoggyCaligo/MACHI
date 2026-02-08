# src/agent/moltbook_executor.py
from __future__ import annotations
import json
from src.agent import moltbook_client

def execute_moltbook_approval(action_type: str, payload_json: str) -> str:
    payload = json.loads(payload_json)

    if action_type == "MOLTBOOK_REGISTER":
        res = moltbook_client.register_agent(payload["name"], payload["description"])
        agent = res.get("agent", {})
        # api_key, claim_url, verification_code :contentReference[oaicite:9]{index=9}
        if agent.get("api_key"):
            moltbook_client.save_creds(agent["api_key"], agent.get("name",""), agent.get("id",""))
        return (
            "등록 완료(아직 활성화 전일 수 있음).\n"
            f"- claim_url: {agent.get('claim_url')}\n"
            f"- verification_code: {agent.get('verification_code')}\n"
            "위 claim_url로 들어가서 X 인증을 끝내면 게시/댓글이 정상 동작."
        )

    creds = moltbook_client.load_creds()
    if not creds:
        return "Moltbook creds 없음. 먼저 /moltbook register 로 등록 후, claim 인증을 완료해야 함."

    if action_type == "MOLTBOOK_POST":
        res = moltbook_client.create_post(payload["title"], payload["content"], payload.get("submolt"), creds.api_key)
        return "POST 결과:\n" + json.dumps(res, ensure_ascii=False, indent=2)

    if action_type == "MOLTBOOK_REPLY":
        res = moltbook_client.reply(payload["post_id"], payload["text"], creds.api_key)
        return "REPLY 결과:\n" + json.dumps(res, ensure_ascii=False, indent=2)

    return "알 수 없는 action_type"
