from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
PROMPTS_DIR = BASE_DIR / "prompts"

DB_PATH = DATA_DIR / "memory.db"

SYSTEM_PROMPT_PATH = PROMPTS_DIR / "system_prompt.txt"
PROJECT_ASK_SYSTEM_PROMPT_PATH = PROMPTS_DIR / "project_ask_system_prompt.txt"
REVIEW_SYSTEM_PROMPT_PATH = PROMPTS_DIR / "review_system_prompt.txt"
PROFILE_EXTRACT_SYSTEM_PROMPT_PATH = PROMPTS_DIR / "profile_extract_system_prompt.txt"
PROJECT_PROFILE_EVIDENCE_EXTRACT_SYSTEM_PROMPT_PATH = (
    PROMPTS_DIR / "project_profile_evidence_extract_system_prompt.txt"
)
PROJECT_PROFILE_EVIDENCE_ANSWER_SYSTEM_PROMPT_PATH = (
    PROMPTS_DIR / "project_profile_evidence_answer_system_prompt.txt"
)
PROFILE_ATTACHMENT_ANSWER_SYSTEM_PROMPT_PATH = (
    PROMPTS_DIR / "profile_attachment_answer_system_prompt.txt"
)

OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_DEFAULT_MODEL = "qwen2.5:3b"
OLLAMA_MODEL = OLLAMA_DEFAULT_MODEL

TOPIC_EMBEDDING_MODEL = "intfloat/multilingual-e5-small"
KEEP_ACTIVE_THRESHOLD = 0.73
ATTACH_EXISTING_THRESHOLD = 0.78
GENERAL_RETENTION_DAYS = 90
TOPIC_SUMMARY_SENTENCE_COUNT = 2
TOPIC_SIMILARITY_CANDIDATE_LIMIT = 12
