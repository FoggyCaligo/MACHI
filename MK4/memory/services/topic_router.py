from __future__ import annotations

import re
import time
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


def _log(message: str) -> None:
    print(f"[MEMORY] {message}", flush=True)


TOPIC_SYSTEM_PROMPT = (
    "사용자 발화의 현재 대주제를 한국어 두 문장으로 요약하라. "
    "세부 사례나 고유명사에 매몰되지 말고, 앞으로 비슷한 대화를 묶을 수 있는 넓은 주제로 작성하라. "
    "사용자 발화를 거의 반복하지 말고, 상위 의미 축으로 정리하라. "
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
            return text[:180].strip()
        return " ".join(sentences[:2])[:180].strip()

    def _safe_default_summary(self) -> str:
        return "general"

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
            return summary or self._safe_default_summary()
        except Exception:
            return self._safe_default_summary()

    def _postprocess_topic_summary(self, summary: str) -> str:
        normalized = self._normalize_summary(summary)
        return normalized or self._safe_default_summary()

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
        started_at = time.perf_counter()
        cleaned = " ".join((user_message or "").strip().split())
        if not cleaned:
            return TopicResolution("general", None, "general", "general", 0.0, False)

        active_topic_id = self.state_store.get_active_topic_id() if use_active_topic else None

        active_check_elapsed = 0.0
        if use_active_topic and active_topic_id:
            t0 = time.perf_counter()
            active_topic = self.topic_store.get_topic(active_topic_id)
            if active_topic:
                similarity = self._active_topic_similarity(cleaned, active_topic)
                active_check_elapsed = time.perf_counter() - t0
                if similarity >= KEEP_ACTIVE_THRESHOLD:
                    self.topic_store.mark_used(active_topic_id)
                    self._persist_active_topic(
                        active_topic_id,
                        active_topic.get("summary") or active_topic.get("name") or "",
                        persist_active=persist_active,
                    )
                    total_elapsed = time.perf_counter() - started_at
                    _log(
                        "topic_router resolve | decision=keep_active | "
                        f"active_check={active_check_elapsed:.2f}s | total={total_elapsed:.2f}s"
                    )
                    return TopicResolution(
                        decision="keep_active",
                        topic_id=active_topic_id,
                        topic_name=active_topic.get("name") or active_topic.get("summary") or "",
                        topic_summary=active_topic.get("summary") or active_topic.get("name") or "",
                        similarity=similarity,
                        used_active_topic=True,
                    )
            else:
                active_check_elapsed = time.perf_counter() - t0

        t0 = time.perf_counter()
        similar_topics = self.topic_store.find_similar_topics(
            text=cleaned,
            limit=TOPIC_SIMILARITY_CANDIDATE_LIMIT,
            min_similarity=ATTACH_EXISTING_THRESHOLD,
            exclude_topic_id=active_topic_id if use_active_topic else None,
        )
        similar_search_elapsed = time.perf_counter() - t0
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
                total_elapsed = time.perf_counter() - started_at
                _log(
                    "topic_router resolve | decision=attach_existing_from_message | "
                    f"active_check={active_check_elapsed:.2f}s | similar_search={similar_search_elapsed:.2f}s | total={total_elapsed:.2f}s"
                )
                return TopicResolution(
                    decision="attach_existing",
                    topic_id=topic_id,
                    topic_name=best.get("name") or summary,
                    topic_summary=summary,
                    similarity=float(best.get("similarity") or 0.0),
                    used_active_topic=False,
                )

        t0 = time.perf_counter()
        new_summary = self._generate_topic_summary(cleaned, model=model)
        new_summary = self._postprocess_topic_summary(new_summary)
        generation_elapsed = time.perf_counter() - t0

        t0 = time.perf_counter()
        summary_matches = self.topic_store.find_similar_topics(
            text=new_summary,
            limit=3,
            min_similarity=ATTACH_EXISTING_THRESHOLD,
            exclude_topic_id=active_topic_id if use_active_topic else None,
        )
        summary_search_elapsed = time.perf_counter() - t0
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
                total_elapsed = time.perf_counter() - started_at
                _log(
                    "topic_router resolve | decision=attach_existing_from_summary | "
                    f"active_check={active_check_elapsed:.2f}s | similar_search={similar_search_elapsed:.2f}s | "
                    f"generate_summary={generation_elapsed:.2f}s | summary_search={summary_search_elapsed:.2f}s | total={total_elapsed:.2f}s"
                )
                return TopicResolution(
                    decision="attach_existing",
                    topic_id=topic_id,
                    topic_name=best.get("name") or summary,
                    topic_summary=summary,
                    similarity=float(best.get("similarity") or 0.0),
                    used_active_topic=False,
                )

        t0 = time.perf_counter()
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
        create_elapsed = time.perf_counter() - t0
        total_elapsed = time.perf_counter() - started_at
        _log(
            "topic_router resolve | decision=create_new | "
            f"active_check={active_check_elapsed:.2f}s | similar_search={similar_search_elapsed:.2f}s | "
            f"generate_summary={generation_elapsed:.2f}s | summary_search={summary_search_elapsed:.2f}s | create={create_elapsed:.2f}s | total={total_elapsed:.2f}s"
        )
        return TopicResolution(
            decision="create_new",
            topic_id=topic_id,
            topic_name=new_summary,
            topic_summary=new_summary,
            similarity=0.0,
            used_active_topic=False,
        )
