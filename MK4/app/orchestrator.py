from app.agent import Agent
from memory.retrieval.response_retriever import ResponseRetriever
from memory.retrieval.recall_retriever import RecallRetriever
from memory.services.chat_evidence_service import ChatEvidenceService
from memory.services.memory_ingress_service import MemoryIngressService
from memory.stores.raw_message_store import RawMessageStore


class Orchestrator:
    def __init__(self) -> None:
        self.agent = Agent()
        self.response_retriever = ResponseRetriever()
        self.recall_retriever = RecallRetriever()
        self.chat_evidence_service = ChatEvidenceService()
        self.memory_ingress_service = MemoryIngressService()
        self.raw_message_store = RawMessageStore()

    def handle_chat(self, user_message: str, model: str | None = None) -> dict:
        self.raw_message_store.add(role="user", content=user_message)
        context = self.response_retriever.retrieve(user_message)
        reply = self.agent.respond(user_message=user_message, context=context, model=model)
        reply = reply.strip()
        if not reply:
            raise RuntimeError("Model returned empty reply")
        self.raw_message_store.add(role="assistant", content=reply)

        update_bundle = self.chat_evidence_service.extract(
            user_message=user_message,
            reply=reply,
            model=model,
        )
        apply_result = self.memory_ingress_service.apply_chat_update(
            user_message=user_message,
            reply=reply,
            update_bundle=update_bundle,
            model=model,
        )

        return {
            "reply": reply,
            "context_used": context,
            "update_plan": update_bundle,
            "memory_apply": apply_result,
        }

    def handle_recall(self, query: str) -> dict:
        return self.recall_retriever.retrieve(query)
