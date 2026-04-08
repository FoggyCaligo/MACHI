import re
import shutil
import uuid
import zipfile
from pathlib import Path

from config import PROFILE_EXTRACT_SYSTEM_PROMPT_PATH
from prompts.prompt_loader import load_prompt_text
from tools.ollama_client import OllamaClient


ALLOWED_TEXT_EXTENSIONS = {".txt", ".md", ".markdown"}
EXCLUDED_DIR_NAMES = {
    ".git", "node_modules", "dist", "build", ".venv", "venv", "__pycache__",
    ".next", ".idea", ".vscode", "coverage",
}
FIRST_PERSON_MARKERS = {
    "나는", "내가", "나의", "저는", "제가", "저의", "i am", "i'm", "my ",
}
PREFERENCE_MARKERS = {
    "좋아", "싫어", "선호", "원한다", "바란다", "중요", "필요", "need",
    "중요", "기준", "습관", "성향", "생각", "판단", "prefer", "want",
    "important", "habit", "style",
}
PROFILE_FILENAME_HINTS = {
    "profile", "blog", "essay", "memo", "notes", "retrospective",
    "회고", "블로그", "프로필", "메모", "생각", "기록",
}


class ProfileExtractService:
    def __init__(self) -> None:
        self.client = OllamaClient(timeout=150, num_predict=768)

    def _load_system_prompt(self) -> str:
        return load_prompt_text(PROFILE_EXTRACT_SYSTEM_PROMPT_PATH)

    def _extract_zip(self, zip_path: Path, target_dir: Path) -> Path:
        target_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(target_dir)
        return target_dir

    def _is_allowed_text_file(self, path: Path) -> bool:
        if path.suffix.lower() not in ALLOWED_TEXT_EXTENSIONS:
            return False

        for part in path.parts:
            if part in EXCLUDED_DIR_NAMES:
                return False

        return True

    def _read_text_file(self, file_path: Path) -> str:
        for encoding in ("utf-8", "utf-8-sig", "cp949"):
            try:
                return file_path.read_text(encoding=encoding)
            except UnicodeDecodeError:
                continue
        return ""

    def _collect_documents(self, root_dir: Path) -> list[dict]:
        documents: list[dict] = []

        for file_path in root_dir.rglob("*"):
            if not file_path.is_file():
                continue

            rel_path = file_path.relative_to(root_dir)
            if not self._is_allowed_text_file(rel_path):
                continue

            content = self._read_text_file(file_path).strip()
            if not content:
                continue

            documents.append(
                {
                    "path": str(rel_path).replace("\\", "/"),
                    "content": content,
                }
            )

        documents.sort(key=lambda x: x["path"])
        return documents

    def _normalize_whitespace(self, text: str) -> str:
        return re.sub(r"\s+", " ", (text or "")).strip()

    def _split_passages(self, content: str) -> list[str]:
        raw_parts = re.split(r"\n\s*\n+", content)
        parts = [self._normalize_whitespace(part) for part in raw_parts]
        parts = [part for part in parts if len(part) >= 40]

        if parts:
            return parts

        lines = [self._normalize_whitespace(line) for line in content.splitlines()]
        lines = [line for line in lines if line]
        grouped: list[str] = []
        bucket: list[str] = []

        for line in lines:
            bucket.append(line)
            joined = " ".join(bucket)
            if len(joined) >= 180:
                grouped.append(joined)
                bucket = []

        if bucket:
            grouped.append(" ".join(bucket))

        return [part for part in grouped if len(part) >= 40]

    def _score_passage(self, passage: str, path: str) -> int:
        lowered = passage.lower()
        path_lower = path.lower()
        score = 0

        for marker in FIRST_PERSON_MARKERS:
            if marker in lowered:
                score += 3

        for marker in PREFERENCE_MARKERS:
            if marker in lowered:
                score += 2

        for hint in PROFILE_FILENAME_HINTS:
            if hint in path_lower:
                score += 1

        if len(passage) >= 250:
            score += 1
        if len(passage) >= 500:
            score += 1

        return score

    def _select_relevant_passages(
        self,
        documents: list[dict],
        max_total_chars: int = 2800,
        max_passages: int = 8,
    ) -> tuple[list[dict], dict]:
        candidates: list[dict] = []
        total_original_chars = 0

        for doc in documents:
            path = doc["path"]
            content = doc["content"]
            total_original_chars += len(content)

            passages = self._split_passages(content)
            for index, passage in enumerate(passages, start=1):
                score = self._score_passage(passage, path)
                candidates.append(
                    {
                        "path": path,
                        "passage_index": index,
                        "score": score,
                        "text": passage,
                    }
                )

        candidates.sort(
            key=lambda item: (
                -item["score"],
                -min(len(item["text"]), 700),
                item["path"],
                item["passage_index"],
            )
        )

        selected: list[dict] = []
        total_chars = 0

        for item in candidates:
            if len(selected) >= max_passages:
                break

            passage_text = item["text"]
            remaining = max_total_chars - total_chars
            if remaining <= 120:
                break

            if len(passage_text) > remaining:
                if remaining < 180:
                    continue
                passage_text = passage_text[:remaining].rstrip() + "..."

            selected.append(
                {
                    "path": item["path"],
                    "passage_index": item["passage_index"],
                    "score": item["score"],
                    "text": passage_text,
                }
            )
            total_chars += len(passage_text)

        if selected:
            return selected, {
                "document_count": len(documents),
                "selected_passage_count": len(selected),
                "selected_chars": total_chars,
                "original_chars": total_original_chars,
                "selection_mode": "self_referential_passages",
            }

        fallback_passages: list[dict] = []
        for doc in documents[:2]:
            content = self._normalize_whitespace(doc["content"])
            if not content:
                continue

            excerpt = content[:1200].rstrip()
            if len(content) > 1200:
                excerpt += "..."
            fallback_passages.append(
                {
                    "path": doc["path"],
                    "passage_index": 1,
                    "score": 0,
                    "text": excerpt,
                }
            )

        selected_chars = sum(len(item["text"]) for item in fallback_passages)

        return fallback_passages, {
            "document_count": len(documents),
            "selected_passage_count": len(fallback_passages),
            "selected_chars": selected_chars,
            "original_chars": total_original_chars,
            "selection_mode": "fallback_head_excerpt",
        }

    def _build_messages(self, user_request: str, documents: list[dict]) -> tuple[list[dict], dict]:
        system_prompt = self._load_system_prompt()
        selected_passages, selection_meta = self._select_relevant_passages(documents)

        blocks = []
        for idx, item in enumerate(selected_passages, start=1):
            blocks.append(
                f"[발췌 {idx}]\n"
                f"경로: {item['path']}\n"
                f"문단 번호: {item['passage_index']}\n"
                f"선별 점수: {item['score']}\n"
                f"본문:\n{item['text']}"
            )

        user_prompt = (
            f"[사용자 요청]\n{user_request}\n\n"
            f"[분석 대상 문서 수]\n{selection_meta['document_count']}\n\n"
            f"[원문 총 길이]\n{selection_meta['original_chars']} chars\n\n"
            f"[선별된 발췌 정보]\n"
            f"- selection_mode: {selection_meta['selection_mode']}\n"
            f"- selected_passage_count: {selection_meta['selected_passage_count']}\n"
            f"- selected_chars: {selection_meta['selected_chars']}\n\n"
            f"[선별된 본문 발췌]\n"
            + "\n\n".join(blocks)
            + "\n\n[주의]\n"
              "전체 원문을 그대로 다 본 것은 아니고, 자기서술/선호/기준/습관이 드러나는 구간을 우선 선별해 분석하라. "
              "따라서 강한 단정 대신 후보와 근거 중심으로 답하라."
        )

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ], selection_meta

    def _extract_from_documents(
        self,
        documents: list[dict],
        user_request: str,
        model: str | None = None,
    ) -> dict:
        if not documents:
            return {
                "answer": "읽을 수 있는 텍스트 자료(.txt, .md, .markdown)를 찾지 못했습니다.",
                "source_files": [],
                "document_count": 0,
                "selected_passage_count": 0,
                "selected_chars": 0,
                "selection_mode": "none",
            }

        messages, selection_meta = self._build_messages(user_request=user_request, documents=documents)
        answer = self.client.chat(messages, model=model)

        return {
            "answer": answer,
            "source_files": [doc["path"] for doc in documents],
            "document_count": len(documents),
            "selected_passage_count": selection_meta["selected_passage_count"],
            "selected_chars": selection_meta["selected_chars"],
            "selection_mode": selection_meta["selection_mode"],
        }

    def extract_from_uploaded_text(
        self,
        filename: str,
        content: str,
        user_request: str,
        model: str | None = None,
    ) -> dict:
        documents = [
            {
                "path": filename or "uploaded_text.txt",
                "content": content.strip(),
            }
        ]
        return self._extract_from_documents(documents=documents, user_request=user_request, model=model)

    def extract_from_zip(
        self,
        zip_path: Path,
        user_request: str,
        extract_root: Path,
        model: str | None = None,
    ) -> dict:
        target_dir = extract_root / str(uuid.uuid4())
        if target_dir.exists():
            shutil.rmtree(target_dir)

        self._extract_zip(zip_path, target_dir)
        documents = self._collect_documents(target_dir)
        return self._extract_from_documents(documents=documents, user_request=user_request, model=model)