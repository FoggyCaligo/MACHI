from __future__ import annotations

import re
from dataclasses import dataclass

from config import (
    ATTACH_EXISTING_THRESHOLD,
    KEEP_ACTIVE_THRESHOLD,
    TOPIC_CREATE_MIN_CONFIDENCE,
    TOPIC_ROUTER_NUM_PREDICT,
    TOPIC_ROUTER_TIMEOUT,
    TOPIC_SIMILARITY_CANDIDATE_LIMIT,
)
from memory.stores.state_store import StateStore
from memory.stores.topic_store import TopicStore
from tools.ollama_client import OllamaClient
from tools.text_embedding import cosine_similarity, embed_text


TOPIC_SYSTEM_PROMPT = (
    "사용자 발화의 현재 대주제를 한국어 두 문장으로 요약하라. "
    "세부 사례나 고유명사에 매몰되지 말고, 앞으로 비슷한 대화를 묶을 수 있는 넓은 주제로 작성하라. "
    "두 문장만 출력하라. 번호, 따옴표, 코드블록, 불릿을 쓰지 마라."
)

TOPIC_BROADEN_SYSTEM_PROMPT = (
    "주제 요약을 더 넓은 대분류로 다듬어라. "
    "사람 이름, 파일명, 모델명, 날짜, 버전, 특정 사건명, 개별 예시, 세부 구현명은 빼고 "
    "나중에 비슷한 대화를 묶을 수 있는 상위 주제로 다시 써라. "
    "한국어 두 문장만 출력하라. 번호, 따옴표, 불릿, 코드블록을 쓰지 마라."
)

SPECIFIC_SUMMARY_PATTERNS = [
    re.compile(r"https?://", re.IGNORECASE),
    re.compile(r"\b[a-z0-9_\-]+\.(py|md|txt|json|yaml|yml|csv|ipynb)\b", re.IGNORECASE),
    re.compile(r"\b[a-z]+\d+(?:\.\d+)*(?::[a-z0-9]+)?\b", re.IGNORECASE),
    re.compile(r"\d{2,}"),
    re.compile(r"[`/\\]"),
    re.compile(r"\[[^\]]+\]|\([^\)]+\)"),
]


@dataclass
class TopicResolution:
    decision: str
    topic_id: str | None
    topic_name: str
    topic_summary: str
    similarity: float
    used_active_topic: bool = False


class TopicRouter:
    def __init__(self) -> None:
        self.topic_store = TopicStore()
        self.state_store = StateStore()

    def _normalize_summary(self, text: str) -> str:
        text = " ".join((text or "").strip().split())
        if not text:
            return ""
        text = text.replace("\n", " ").strip(' "\'')
        sentences = re.split(r"(?<=[.!?。！？])\s+", text)
        sentences = [s.strip() for s in sentences if s.strip()]
        if not sentences:
            return text[:180].strip()
        return " ".join(sentences[:2])[:180].strip()

    def _fallback_topic_summary(self, user_message: str) -> str:
        text = " ".join((user_message or "").strip().split())
        if not text:
            return "general"
        sentences = re.split(r"(?<=[.!?。！？])\s+", text)
        sentences = [s.strip() for s in sentences if s.strip()]
        if sentences:
            return " ".join(sentences[:2])[:180].strip()
        return text[:180].strip()

    def _generate_topic_summary(self, user_message: str, model: str | None = None) -> str:
        client = OllamaClient(timeout=TOPIC_ROUTER_TIMEOUT, num_predict=TOPIC_ROUTER_NUM_PREDICT)
        try:
            content = client.chat(
                [
                    {"role": "system", "content": TOPIC_SYSTEM_PROMPT},
                    {"role": "user", "content": " ".join((user_message or "").strip().split())[:900]},
                ],
                model=model,
                require_complete=False,
                truncated_notice="",
            )
            summary = self._normalize_summary(content)
            return summary or self._fallback_topic_summary(user_message)
        except Exception:
            return self._fallback_topic_summary(user_message)

    def _contains_specific_markers(self, summary: str) -> bool:
        return any(pattern.search(summary or "") for pattern in SPECIFIC_SUMMARY_PATTERNS)

    def _content_overlap_ratio(self, summary: str, user_message: str) -> float:
        summary_tokens = [
            token for token in re.findall(r"[가-힣A-Za-z0-9_\-]+", summary.lower()) if len(token) >= 2
        ]
        if not summary_tokens:
            return 0.0
        message_tokens = set(
            token for token in re.findall(r"[가-힣A-Za-z0-9_\-]+", user_message.lower()) if len(token) >= 2
        )
        if not message_tokens:
            return 0.0
        overlap = sum(1 for token in summary_tokens if token in message_tokens)
        return overlap / max(len(summary_tokens), 1)

    def _needs_broadening(self, summary: str, user_message: str) -> bool:
        normalized = self._normalize_summary(summary)
        if not normalized or normalized.lower() == "general":
            return False
        if len(normalized) >= 120:
            return True
        if self._contains_specific_markers(normalized):
            return True
        if self._content_overlap_ratio(normalized, user_message) >= 0.8 and len(normalized) >= 60:
            return True
        return False

    def _broaden_topic_summary(self, summary: str, user_message: str, model: str | None = None) -> str:
        client = OllamaClient(timeout=TOPIC_ROUTER_TIMEOUT, num_predict=max(48, TOPIC_ROUTER_NUM_PREDICT // 2))
        try:
            content = client.chat(
                [
                    {"role": "system", "content": TOPIC_BROADEN_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            f"[원문 발화]\n{user_message[:700]}\n\n"
                            f"[현재 주제 요약]\n{summary[:220]}"
                        ),
                    },
                ],
                model=model,
                require_complete=False,
                truncated_notice="",
            )
            return self._normalize_summary(content)
        except Exception:
            return ""

    def _postprocess_topic_summary(self, summary: str, user_message: str, model: str | None = None) -> str:
        normalized = self._normalize_summary(summary)
        if not normalized:
            return self._fallback_topic_summary(user_message)

        if self._needs_broadening(normalized, user_message):
            broadened = self._broaden_topic_summary(normalized, user_message, model=model)
            if broadened:
                normalized = broadened

        return self._normalize_summary(normalized) or self._fallback_topic_summary(user_message)

    def _active_topic_similarity(self, user_message: str, topic: dict) -> float:
        query_embedding = embed_text(user_message, kind="query")
        return cosine_similarity(query_embedding, topic.get("embedding") or [])

    def _persist_active_topic(
        self,
        topic_id: str | None,
        summary: str,
        *,
        persist_active: bool,
    ) -> None:
        if not persist_active or not topic_id:
            return
        self.state_store.set_active_topic(topic_id, summary, source="topic_router")

    def resolve(
        self,
        user_message: str,
        model: str | None = None,
        *,
        use_active_topic: bool = True,
        persist_active: bool = True,
    ) -> TopicResolution:
        cleaned = " ".join((user_message or "").strip().split())
        if not cleaned:
            return TopicResolution("general", None, "general", "general", 0.0, False)

        active_topic_id = self.state_store.get_active_topic_id() if use_active_topic else None

        if use_active_topic and active_topic_id:
            active_topic = self.topic_store.get_topic(active_topic_id)
            if active_topic:
                similarity = self._active_topic_similarity(cleaned, active_topic)
                if similarity >= KEEP_ACTIVE_THRESHOLD:
                    self.topic_store.mark_used(active_topic_id)
                    self._persist_active_topic(
                        active_topic_id,
                        active_topic.get("summary") or active_topic.get("name") or "",
                        persist_active=persist_active,
                    )
                    return TopicResolution(
                        decision="keep_active",
                        topic_id=active_topic_id,
                        topic_name=active_topic.get("name") or active_topic.get("summary") or "",
                        topic_summary=active_topic.get("summary") or active_topic.get("name") or "",
                        similarity=similarity,
                        used_active_topic=True,
                    )

        similar_topics = self.topic_store.find_similar_topics(
            text=cleaned,
            limit=TOPIC_SIMILARITY_CANDIDATE_LIMIT,
            min_similarity=ATTACH_EXISTING_THRESHOLD,
            exclude_topic_id=active_topic_id if use_active_topic else None,
        )
        if similar_topics:
            best = similar_topics[0]
            topic_id = str(best.get("id") or "").strip() or None
            if topic_id:
                self.topic_store.mark_used(topic_id)
                summary = best.get("summary") or best.get("name") or ""
                self._persist_active_topic(
                    topic_id,
                    summary,
                    persist_active=persist_active,
                )
                return TopicResolution(
                    decision="attach_existing",
                    topic_id=topic_id,
                    topic_name=best.get("name") or summary,
                    topic_summary=summary,
                    similarity=float(best.get("similarity") or 0.0),
                    used_active_topic=False,
                )

        new_summary = self._generate_topic_summary(cleaned, model=model)
        new_summary = self._postprocess_topic_summary(new_summary, cleaned, model=model)

        summary_matches = self.topic_store.find_similar_topics(
            text=new_summary,
            limit=3,
            min_similarity=ATTACH_EXISTING_THRESHOLD,
            exclude_topic_id=active_topic_id if use_active_topic else None,
        )
        if summary_matches:
            best = summary_matches[0]
            topic_id = str(best.get("id") or "").strip() or None
            if topic_id:
                self.topic_store.mark_used(topic_id)
                summary = best.get("summary") or best.get("name") or new_summary
                self._persist_active_topic(
                    topic_id,
                    summary,
                    persist_active=persist_active,
                )
                return TopicResolution(
                    decision="attach_existing",
                    topic_id=topic_id,
                    topic_name=best.get("name") or summary,
                    topic_summary=summary,
                    similarity=float(best.get("similarity") or 0.0),
                    used_active_topic=False,
                )

        topic_id = self.topic_store.create_topic(
            name=new_summary,
            summary=new_summary,
            source="topic_router",
            confidence=TOPIC_CREATE_MIN_CONFIDENCE,
        )
        self.topic_store.mark_used(topic_id)
        self._persist_active_topic(
            topic_id,
            new_summary,
            persist_active=persist_active,
        )
        return TopicResolution(
            decision="create_new",
            topic_id=topic_id,
            topic_name=new_summary,
            topic_summary=new_summary,
            similarity=0.0,
            used_active_topic=False,
        )
