from __future__ import annotations

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "gemma4:26b-a4b-it-q4_K_M")
    ollama_timeout_seconds: int = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "180"))
    ollama_context_length: int = int(os.getenv("OLLAMA_CONTEXT_LENGTH", "32768"))

    ollama_api_key: str = os.getenv("OLLAMA_API_KEY", "")
    ollama_web_search_url: str = os.getenv("OLLAMA_WEB_SEARCH_URL", "https://ollama.com/api/web_search")
    internet_search_enabled: bool = os.getenv("INTERNET_SEARCH_ENABLED", "true").lower() == "true"
    max_search_results: int = int(os.getenv("MAX_SEARCH_RESULTS", "8"))

    app_host: str = os.getenv("APP_HOST", "127.0.0.1")
    app_port: int = int(os.getenv("APP_PORT", "8000"))
    recent_message_limit: int = int(os.getenv("RECENT_MESSAGE_LIMIT", "12"))
    max_tool_rounds: int = int(os.getenv("MAX_TOOL_ROUNDS", "4"))
    enable_memory: bool = os.getenv("ENABLE_MEMORY", "true").lower() == "true"

    data_dir: str = "data"
    sqlite_path: str = os.path.join("data", "chat_history.db")
    profile_path: str = os.path.join("data", "user_profile.json")


settings = Settings()
