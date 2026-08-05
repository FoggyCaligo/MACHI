from project_analysis.stores.project_file_store import ProjectFileStore
from project_analysis.stores.project_review_store import ProjectReviewStore
from project_analysis.review.review_agent import ReviewAgent


class ProjectReviewService:
    def __init__(self) -> None:
        self.project_file_store = ProjectFileStore()
        self.project_review_store = ProjectReviewStore()
        self.review_agent = ReviewAgent()

    def review_file(self, project_id: str, path: str, question: str) -> dict:
        target_file = self.project_file_store.get_by_path(project_id, path)
        if not target_file:
            raise ValueError(f"File not found: {path}")

        answer = self.review_agent.review_file(
            file_path=target_file["path"],
            code_content=target_file["content"],
            question=question,
        )

        self.project_review_store.add(
            project_id=project_id,
            question=question,
            answer=answer,
        )

        return {
            "project_id": project_id,
            "path": target_file["path"],
            "question": question,
            "answer": answer,
        }