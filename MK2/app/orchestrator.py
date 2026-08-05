from __future__ import annotations

import time

from app.agent import Agent
from memory.retrieval.response_retriever import ResponseRetriever
from memory.retrieval.recall_retriever import RecallRetriever
from memory.services.chat_evidence_service import ChatEvidenceService
from memory.services.memory_ingress_service import MemoryIngressService
from memory.stores.raw_message_store import RawMessageStore


def _log(message: str) -> None:
    print(f"[ORCHESTRATOR] {message}", flush=True)


class Orchestrator:
    def __init__(self) -> None:
        self.agent = Agent()
        self.response_retriever = ResponseRetriever()
        self.recall_retriever = RecallRetriever()
        self.chat_evidence_service = ChatEvidenceService()
        self.memory_ingress_service = MemoryIngressService()
        self.raw_message_store = RawMessageStore()

    def handle_chat(self, user_message: str, model: str | None = None) -> dict:
        started_at = time.perf_counter()

        t0 = time.perf_counter()
        source_message_id = self.raw_message_store.add(role="user", content=user_message)
        raw_user_elapsed = time.perf_counter() - t0

        t0 = time.perf_counter()
        context = self.response_retriever.retrieve(user_message)
        retrieval_elapsed = time.perf_counter() - t0

        t0 = time.perf_counter()
        reply = self.agent.respond(user_message=user_message, context=context, model=model)
        agent_elapsed = time.perf_counter() - t0

        reply = reply.strip()
        if not reply:
            raise RuntimeError("Model returned empty reply")

        t0 = time.perf_counter()
        response_message_id = self.raw_message_store.add(role="assistant", content=reply)
        raw_assistant_elapsed = time.perf_counter() - t0

        t0 = time.perf_counter()
        update_bundle = self.chat_evidence_service.extract(
            user_message=user_message,
            reply=reply,
            model=model,
        )
        update_extract_elapsed = time.perf_counter() - t0

        t0 = time.perf_counter()
        apply_result = self.memory_ingress_service.apply_chat_update(
            user_message=user_message,
            reply=reply,
            update_bundle=update_bundle,
            model=model,
            source_message_id=source_message_id,
            response_message_id=response_message_id,
        )
        memory_update_elapsed = time.perf_counter() - t0

        total_elapsed = time.perf_counter() - started_at
        _log(
            "handle_chat timing | "
            f"raw_user={raw_user_elapsed:.2f}s | "
            f"retrieve={retrieval_elapsed:.2f}s | "
            f"agent={agent_elapsed:.2f}s | "
            f"raw_assistant={raw_assistant_elapsed:.2f}s | "
            f"update_extract={update_extract_elapsed:.2f}s | "
            f"memory_update={memory_update_elapsed:.2f}s | "
            f"total={total_elapsed:.2f}s"
        )

        return {
            "reply": reply,
            "context_used": context,
            "update_plan": update_bundle,
            "memory_apply": apply_result,
        }

    def handle_recall(self, query: str) -> dict:
        return self.recall_retriever.retrieve(query)
