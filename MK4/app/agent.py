from config import (
    GENERAL_REPLY_MAX_CONTINUATIONS,
    GENERAL_REPLY_NUM_PREDICT,
    GENERAL_REPLY_TIMEOUT,
)
from prompts.response_builder import build_messages
from tools.reply_guard import build_guard_context
from tools.response_runner import ResponseRunner


class Agent:
    def __init__(self) -> None:
        self.runner = ResponseRunner(
            timeout=GENERAL_REPLY_TIMEOUT,
            num_predict=GENERAL_REPLY_NUM_PREDICT,
            max_continuations=GENERAL_REPLY_MAX_CONTINUATIONS,
        )

    def respond(self, user_message: str, context: dict, model: str | None = None) -> str:
        enriched_context = dict(context)
        enriched_context["reply_guard"] = build_guard_context(context).to_dict()
        messages = build_messages(user_message=user_message, context=enriched_context)
        result = self.runner.run(messages, model=model)
        return result.text
