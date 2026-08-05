import uuid
from datetime import datetime, timezone

from project_analysis.stores.db import get_conn


class ProjectReviewStore:
    def add(self, project_id: str, question: str, answer: str) -> dict:
        review_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO project_reviews (id, project_id, question, answer, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (review_id, project_id, question, answer, now),
            )
            conn.commit()

        return {
            "id": review_id,
            "project_id": project_id,
            "question": question,
            "answer": answer,
            "created_at": now,
        }