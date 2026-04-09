from config import (
    GENERAL_REPLY_MAX_CONTINUATIONS,
    GENERAL_REPLY_NUM_PREDICT,
    GENERAL_REPLY_TIMEOUT,
)
from prompts.response_builder import build_messages
from tools.reply_guard import maybe_build_direct_reply
from tools.response_runner import ResponseRunner


class Agent:
    def __init__(self) -> None:
        self.runner = ResponseRunner(
            timeout=GENERAL_REPLY_TIMEOUT,
            num_predict=GENERAL_REPLY_NUM_PREDICT,
            max_continuations=GENERAL_REPLY_MAX_CONTINUATIONS,
        )

    def respond(self, user_message: str, context: dict, model: str | None = None) -> str:
        direct_reply = maybe_build_direct_reply(user_message=user_message, context=context)
        if direct_reply:
            return direct_reply

        messages = build_messages(user_message=user_message, context=context)
        result = self.runner.run(messages, model=model)
        return result.text
