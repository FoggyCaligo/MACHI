from prompts.response_builder import build_messages
from tools.ollama_client import OllamaClient


class Agent:
    def __init__(self) -> None:
        self.client = OllamaClient()

    def respond(self, user_message: str, context: dict) -> str:
        messages = build_messages(user_message=user_message, context=context)
        return self.client.chat(messages)
