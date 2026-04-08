from tools.ollama_client import OllamaClient
from project_analysis.review.review_prompt_builder import build_file_review_messages


class ReviewAgent:
    def __init__(self) -> None:
        self.client = OllamaClient()

    def review_file(self, file_path: str, code_content: str, question: str) -> str:
        messages = build_file_review_messages(
            file_path=file_path,
            code_content=code_content,
            question=question,
        )
        return self.client.chat(messages)