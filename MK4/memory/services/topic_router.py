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
            return text[:160].strip()
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

    def _active_topic_similarity(self, user_message: str, topic: dict) -> float:
        query_embedding = embed_text(user_message, kind="query")
        return cosine_similarity(query_embedding, topic.get("embedding") or [])

    def resolve(self, user_message: str, model: str | None = None) -> TopicResolution:
        cleaned = " ".join((user_message or "").strip().split())
        if not cleaned:
            return TopicResolution("general", None, "general", "general", 0.0, False)

        active_topic_id = self.state_store.get_active_topic_id()
        if active_topic_id:
            active_topic = self.topic_store.get_topic(active_topic_id)
            if active_topic:
                similarity = self._active_topic_similarity(cleaned, active_topic)
                if similarity >= KEEP_ACTIVE_THRESHOLD:
                    self.topic_store.mark_used(active_topic_id)
                    self.state_store.set_active_topic(
                        active_topic_id,
                        active_topic.get("summary") or active_topic.get("name") or "",
                        source="topic_router",
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
            exclude_topic_id=active_topic_id,
        )
        if similar_topics:
            best = similar_topics[0]
            topic_id = str(best.get("id") or "").strip() or None
            if topic_id:
                self.topic_store.mark_used(topic_id)
                summary = best.get("summary") or best.get("name") or ""
                self.state_store.set_active_topic(topic_id, summary, source="topic_router")
                return TopicResolution(
                    decision="attach_existing",
                    topic_id=topic_id,
                    topic_name=best.get("name") or summary,
                    topic_summary=summary,
                    similarity=float(best.get("similarity") or 0.0),
                    used_active_topic=False,
                )

        new_summary = self._generate_topic_summary(cleaned, model=model)
        topic_id = self.topic_store.create_topic(
            name=new_summary,
            summary=new_summary,
            source="topic_router",
            confidence=TOPIC_CREATE_MIN_CONFIDENCE,
        )
        self.topic_store.mark_used(topic_id)
        self.state_store.set_active_topic(topic_id, new_summary, source="topic_router")
        return TopicResolution(
            decision="create_new",
            topic_id=topic_id,
            topic_name=new_summary,
            topic_summary=new_summary,
            similarity=0.0,
            used_active_topic=False,
        )
