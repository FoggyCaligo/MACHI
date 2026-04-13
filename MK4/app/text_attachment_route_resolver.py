from __future__ import annotations

import json
import re

from config import OLLAMA_DEFAULT_MODEL, ROUTE_CLASSIFY_NUM_PREDICT
from tools.ollama_client import OllamaClient


class TextAttachmentRouteResolver:
    def __init__(self) -> None:
        self.client = OllamaClient(timeout=45, num_predict=ROUTE_CLASSIFY_NUM_PREDICT)

    def _excerpt(self, content: str, max_chars: int = 800) -> str:
        compact = re.sub(r"\s+", " ", (content or "")).strip()
        return compact[:max_chars]

    def resolve(self, *, user_request: str, filename: str, content: str, model: str | None = None) -> str:
        system_prompt = (
            "첨부 텍스트 요청의 처리 경로를 결정하라.\n"
            "JSON만 출력: {\"route\": \"profile_update\"} 또는 {\"route\": \"general_chat\"}\n"
            "\n"
            "profile_update를 선택하는 경우:\n"
            "- 사용자가 첨부 글을 통해 자신의 성향, 성격, 선호, 사고방식, 가치관을 파악하거나 업데이트하길 원할 때\n"
            "- '나 어때', '내 성격', '내 성향', '프로필', '나를 파악', '나에 대해', '내가 어떤 사람' 등의 표현이 포함될 때\n"
            "- 사용자 본인이 쓴 글(블로그, 일기, 에세이 등)을 분석 대상으로 제시할 때\n"
            "\n"
            "general_chat을 선택하는 경우:\n"
            "- 첨부 글의 내용에 대한 질문, 요약, 의견, 번역 등 일반적인 참고 자료로 쓸 때\n"
            "- 사용자 본인과 무관한 외부 문서나 자료를 첨부할 때\n"
            "\n"
            "판단이 애매하면 profile_update보다 general_chat을 선택하라."
        )
        user_prompt = json.dumps(
            {
                "filename": filename,
                "user_request": (user_request or "")[:600],
                "attachment_excerpt": self._excerpt(content),
            },
            ensure_ascii=False,
        )
        try:
            raw = self.client.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                model=model or OLLAMA_DEFAULT_MODEL,
                require_complete=False,
            )
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if not match:
                return "general_chat"
            data = json.loads(match.group(0))
            route = str(data.get("route") or "").strip()
            return route if route in {"profile_update", "general_chat"} else "general_chat"
        except Exception:
            return "general_chat"