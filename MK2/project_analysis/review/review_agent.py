from config import (
    PROJECT_REPLY_MAX_CONTINUATIONS,
    PROJECT_REPLY_NUM_PREDICT,
    PROJECT_REPLY_TIMEOUT,
)
from project_analysis.review.review_prompt_builder import build_file_review_messages
from tools.response_runner import ResponseRunner


class ReviewAgent:
    def __init__(self) -> None:
        self.runner = ResponseRunner(
            timeout=PROJECT_REPLY_TIMEOUT,
            num_predict=PROJECT_REPLY_NUM_PREDICT,
            max_continuations=PROJECT_REPLY_MAX_CONTINUATIONS,
        )

    def review_file(self, file_path: str, code_content: str, question: str) -> str:
        messages = build_file_review_messages(
            file_path=file_path,
            code_content=code_content,
            question=question,
        )
        return self.runner.run(messages).text
