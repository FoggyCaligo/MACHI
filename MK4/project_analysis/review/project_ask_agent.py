from config import (
    PROJECT_REPLY_MAX_CONTINUATIONS,
    PROJECT_REPLY_NUM_PREDICT,
    PROJECT_REPLY_TIMEOUT,
)
from project_analysis.review.project_ask_prompt_builder import build_project_ask_messages
from tools.response_runner import ResponseRunner


class ProjectAskAgent:
    def __init__(self) -> None:
        self.runner = ResponseRunner(
            timeout=PROJECT_REPLY_TIMEOUT,
            num_predict=PROJECT_REPLY_NUM_PREDICT,
            max_continuations=PROJECT_REPLY_MAX_CONTINUATIONS,
        )

    def ask(self, question: str, chunks: list[dict], model: str | None = None) -> str:
        messages = build_project_ask_messages(
            question=question,
            chunks=chunks,
        )
        return self.runner.run(messages, model=model).text
