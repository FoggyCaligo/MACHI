from memory.services.memory_ingress_service import MemoryIngressService
from project_analysis.retrieval.project_retriever import ProjectRetriever
from project_analysis.review.project_ask_agent import ProjectAskAgent
from project_analysis.services.project_profile_evidence_service import ProjectProfileEvidenceService
from project_analysis.services.project_profile_route_resolver import ProjectProfileRouteResolver
from project_analysis.stores.project_review_store import ProjectReviewStore


class ProjectAskService:
    def __init__(self) -> None:
        self.retriever = ProjectRetriever()
        self.ask_agent = ProjectAskAgent()
        self.profile_evidence_service = ProjectProfileEvidenceService()
        self.profile_route_resolver = ProjectProfileRouteResolver()
        self.memory_ingress_service = MemoryIngressService()
        self.project_review_store = ProjectReviewStore()

    def ask(self, project_id: str, question: str, model: str | None = None) -> dict:
        profile_extract_result = None
        profile_sync_result = None

        route = self.profile_route_resolver.resolve(question=question, model=model)
        if route == "profile_question":
            profile_extract_result = self.profile_evidence_service.ensure_extracted(project_id, model=model)
            if profile_extract_result.get("needs_memory_sync"):
                profile_sync_result = self.memory_ingress_service.sync_project(project_id)

            profile_result = self.profile_evidence_service.answer_from_project(
                project_id,
                question,
                model=model,
            )
            if profile_result:
                self.project_review_store.add(
                    project_id=project_id,
                    question=question,
                    answer=profile_result["answer"],
                )
                return {
                    "project_id": project_id,
                    "question": question,
                    "answer": profile_result["answer"],
                    "used_chunks": [],
                    "used_profile_evidence": profile_result.get("used_profile_evidence", []),
                    "profile_evidence_extract": profile_extract_result,
                    "profile_memory_sync": profile_sync_result,
                }

        chunks = self.retriever.retrieve(
            project_id=project_id,
            question=question,
            top_k=5,
        )

        answer = self.ask_agent.ask(
            question=question,
            chunks=chunks,
            model=model,
        )

        self.project_review_store.add(
            project_id=project_id,
            question=question,
            answer=answer,
        )

        used_chunks = [
            {
                "file_path": c["file_path"],
                "start_line": c["start_line"],
                "end_line": c["end_line"],
                "score": c["score"],
            }
            for c in chunks
        ]

        return {
            "project_id": project_id,
            "question": question,
            "answer": answer,
            "used_chunks": used_chunks,
            "used_profile_evidence": [],
            "profile_evidence_extract": profile_extract_result,
            "profile_memory_sync": profile_sync_result,
        }
