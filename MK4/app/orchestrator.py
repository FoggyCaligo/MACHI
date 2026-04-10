from app.agent import Agent
from memory.retrieval.response_retriever import ResponseRetriever
from memory.retrieval.recall_retriever import RecallRetriever
from memory.retrieval.update_retriever import UpdateRetriever
from memory.policies.extraction_policy import ExtractionPolicy
from memory.policies.conflict_policy import ConflictPolicy
from memory.policies.retention_policy import RetentionPolicy
from memory.stores.raw_message_store import RawMessageStore


class Orchestrator:
    def __init__(self) -> None:
        self.agent = Agent()
        self.response_retriever = ResponseRetriever()
        self.recall_retriever = RecallRetriever()
        self.update_retriever = UpdateRetriever()
        self.extraction_policy = ExtractionPolicy()
        self.conflict_policy = ConflictPolicy()
        self.retention_policy = RetentionPolicy()
        self.raw_message_store = RawMessageStore()

    def handle_chat(self, user_message: str, model: str | None = None) -> dict:
        self.raw_message_store.add(role="user", content=user_message)
        context = self.response_retriever.retrieve(user_message)
        reply = self.agent.respond(user_message=user_message, context=context, model=model)
        reply = reply.strip()
        if not reply:
            raise RuntimeError("Model returned empty reply")
        self.raw_message_store.add(role="assistant", content=reply)
        update_plan = self.update_retriever.classify(user_message=user_message, reply=reply, model=model)
        extracted = self.extraction_policy.extract(user_message=user_message, reply=reply, update_plan=update_plan, model=model)
        self.conflict_policy.apply(extracted)
        self.retention_policy.run()

        return {
            "reply": reply,
            "context_used": context,
            "update_plan": update_plan,
        }

    def handle_recall(self, query: str) -> dict:
        return self.recall_retriever.retrieve(query)