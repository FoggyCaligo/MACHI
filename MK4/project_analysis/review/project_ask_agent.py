from tools.ollama_client import OllamaClient
from project_analysis.review.project_ask_prompt_builder import build_project_ask_messages


class ProjectAskAgent:
    def __init__(self) -> None:
        self.client = OllamaClient()

    def ask(self, question: str, chunks: list[dict], model: str | None = None) -> str:
        messages = build_project_ask_messages(
            question=question,
            chunks=chunks,
        )
        return self.client.chat(messages, model=model)