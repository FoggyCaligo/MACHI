from app.agent import Agent
from memory.retrieval.response_retriever import ResponseRetriever
from memory.retrieval.recall_retriever import RecallRetriever
from memory.retrieval.update_retriever import UpdateRetriever
from memory.policies.extraction_policy import ExtractionPolicy
from memory.policies.conflict_policy import ConflictPolicy
from memory.policies.retention_policy import RetentionPolicy
from memory.stores.state_store import StateStore


class Orchestrator:
    def __init__(self) -> None:
        self.agent = Agent()
        self.response_retriever = ResponseRetriever()
        self.recall_retriever = RecallRetriever()
        self.update_retriever = UpdateRetriever()
        self.extraction_policy = ExtractionPolicy()
        self.conflict_policy = ConflictPolicy()
        self.retention_policy = RetentionPolicy()
        self.state_store = StateStore()

    def handle_chat(self, user_message: str) -> dict:
        context = self.response_retriever.retrieve(user_message)
        reply = self.agent.respond(user_message=user_message, context=context)

        update_plan = self.update_retriever.classify(user_message=user_message, reply=reply)
        extracted = self.extraction_policy.extract(user_message=user_message, reply=reply, update_plan=update_plan)
        self.conflict_policy.apply(extracted)
        self.retention_policy.run()

        return {
            "reply": reply,
            "context_used": context,
            "update_plan": update_plan,
        }

    def handle_recall(self, query: str) -> dict:
        return self.recall_retriever.retrieve(query)
