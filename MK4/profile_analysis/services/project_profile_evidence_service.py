import json
from pathlib import Path

from config import (
    PROJECT_PROFILE_EVIDENCE_ANSWER_SYSTEM_PROMPT_PATH,
    PROJECT_PROFILE_EVIDENCE_EXTRACT_SYSTEM_PROMPT_PATH,
)
from profile_analysis.services.profile_memory_sync_service import ProfileMemorySyncService
from prompts.prompt_loader import load_prompt_text
from project_analysis.stores.project_file_store import ProjectFileStore
from project_analysis.stores.project_profile_evidence_store import ProjectProfileEvidenceStore
from tools.ollama_client import OllamaClient


PROFILE_DOC_EXTENSIONS = {".txt", ".md", ".markdown", ".rst"}
PROFILE_NAME_HINTS = {
    "readme.md",
    "readme.txt",
    "about.md",
    "profile.md",
    "notes.md",
    "blog.md",
    "blog.txt",
    "plan.md",
    "planning.md",
    "retrospective.md",
}
PROFILE_QUESTION_KEYWORDS = {
    "성향",
    "프로필",
    "스타일",
    "선호",
    "need",
    "니즈",
    "작동 방식",
    "나에 대해",
    "어떤 사람",
    "나답",
    "습관",
    "판단 기준",
    "불편해하는",
}
SOURCE_STRENGTH_ORDER = {
    "temporary_interest": 1,
    "repeated_behavior": 2,
    "explicit_self_statement": 3,
}


class ProjectProfileEvidenceService:
    def __init__(self) -> None:
        self.file_store = ProjectFileStore()
        self.evidence_store = ProjectProfileEvidenceStore()
        self.sync_service = ProfileMemorySyncService()
        self.extract_client = OllamaClient(timeout=150, num_predict=640)
        self.answer_client = OllamaClient(timeout=120, num_predict=420)

    def is_profile_question(self, question: str) -> bool:
        q = (question or "").lower()
        return any(keyword in q for keyword in PROFILE_QUESTION_KEYWORDS)

    def _select_documents(self, project_id: str) -> list[dict]:
        files = self.file_store.list_full_by_project(project_id)
        selected: list[dict] = []

        for file in files:
            path = file.get("path") or ""
            ext = (file.get("ext") or "").lower()
            name = Path(path).name.lower()
            content = (file.get("content") or "").strip()

            if not content:
                continue

            if ext in PROFILE_DOC_EXTENSIONS or name in PROFILE_NAME_HINTS:
                selected.append(
                    {
                        "path": path,
                        "content": content,
                    }
                )

        return selected[:8]

    def _build_extract_messages(self, project_id: str, documents: list[dict]) -> list[dict]:
        system_prompt = load_prompt_text(PROJECT_PROFILE_EVIDENCE_EXTRACT_SYSTEM_PROMPT_PATH)

        blocks = []
        for idx, doc in enumerate(documents, start=1):
            content = doc["content"]
            if len(content) > 2800:
                content = content[:2800].rstrip() + "\n..."

            blocks.append(
                f"[자료 {idx}]\n"
                f"프로젝트: {project_id}\n"
                f"경로: {doc['path']}\n"
                f"본문:\n{content}"
            )

        user_prompt = "[분석 자료]\n" + "\n\n".join(blocks)

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    def _build_answer_messages(self, question: str, evidences: list[dict]) -> list[dict]:
        system_prompt = load_prompt_text(PROJECT_PROFILE_EVIDENCE_ANSWER_SYSTEM_PROMPT_PATH)

        blocks = []
        for idx, evidence in enumerate(evidences[:8], start=1):
            text = (evidence.get("evidence_text") or "").strip()
            if len(text) > 700:
                text = text[:700].rstrip() + "\n..."

            blocks.append(
                f"[evidence {idx}]\n"
                f"topic: {evidence.get('topic')}\n"
                f"candidate_content: {evidence.get('candidate_content')}\n"
                f"source_strength: {evidence.get('source_strength')}\n"
                f"source_file_path: {evidence.get('source_file_path')}\n"
                f"confidence: {evidence.get('confidence')}\n"
                f"근거: {text}"
            )

        user_prompt = (
            f"[질문]\n{question}\n\n"
            f"[프로필 evidence]\n" + "\n\n".join(blocks)
        )

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    def _extract_json_array(self, text: str) -> list[dict]:
        raw = (text or "").strip()
        if not raw:
            return []

        if raw.startswith("```"):
            lines = raw.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            raw = "\n".join(lines).strip()

        start = raw.find("[")
        end = raw.rfind("]")
        if start == -1 or end == -1 or end < start:
            return []

        raw = raw[start:end + 1]

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []

        if not isinstance(data, list):
            return []

        result: list[dict] = []
        for item in data:
            if not isinstance(item, dict):
                continue

            topic = str(item.get("topic") or "").strip()
            candidate_content = str(item.get("candidate_content") or "").strip()
            source_strength = str(item.get("source_strength") or "").strip()
            evidence_text = str(item.get("evidence_text") or "").strip()

            try:
                confidence = float(item.get("confidence", 0.0))
            except (TypeError, ValueError):
                confidence = 0.0

            source_file_paths = item.get("source_file_paths") or []
            if not isinstance(source_file_paths, list):
                source_file_paths = []

            if not topic or not candidate_content:
                continue

            if source_strength not in SOURCE_STRENGTH_ORDER:
                source_strength = "repeated_behavior"

            result.append(
                {
                    "topic": topic,
                    "candidate_content": candidate_content,
                    "source_strength": source_strength,
                    "confidence": max(0.0, min(confidence, 1.0)),
                    "evidence_text": evidence_text,
                    "source_file_paths": [str(x) for x in source_file_paths],
                }
            )

        return result

    def extract_and_store(self, project_id: str, model: str | None = None) -> dict:
        documents = self._select_documents(project_id)
        self.evidence_store.delete_by_project(project_id)

        if not documents:
            return {
                "stored": False,
                "document_count": 0,
                "source_files": [],
                "candidate_count": 0,
            }

        messages = self._build_extract_messages(project_id=project_id, documents=documents)
        answer = self.extract_client.chat(
            messages,
            model=model,
            require_complete=True,
            truncated_notice=None,
        ).strip()
        candidates = self._extract_json_array(answer)

        for candidate in candidates:
            source_paths = candidate.get("source_file_paths") or []
            source_file_path = ", ".join(source_paths) if source_paths else "__unknown__"

            self.evidence_store.add(
                project_id=project_id,
                source_file_path=source_file_path,
                evidence_type="profile_candidate",
                topic=candidate["topic"],
                candidate_content=candidate["candidate_content"],
                source_strength=candidate["source_strength"],
                evidence_text=candidate["evidence_text"],
                confidence=candidate["confidence"],
            )

        return {
            "stored": True,
            "document_count": len(documents),
            "source_files": [doc["path"] for doc in documents],
            "candidate_count": len(candidates),
        }

    def sync_to_memory(self, project_id: str) -> dict:
        return self.sync_service.sync_project(project_id)

    def answer_from_project(
        self,
        project_id: str,
        question: str,
        model: str | None = None,
    ) -> dict | None:
        evidences = self.evidence_store.list_by_project(project_id)
        if not evidences:
            self.extract_and_store(project_id, model=model)
            self.sync_to_memory(project_id)
            evidences = self.evidence_store.list_by_project(project_id)

        if not evidences:
            return None

        messages = self._build_answer_messages(question=question, evidences=evidences)
        answer = self.answer_client.chat(messages, model=model)

        used_evidence = [
            {
                "topic": item.get("topic"),
                "source_file_path": item.get("source_file_path"),
                "confidence": item.get("confidence"),
                "source_strength": item.get("source_strength"),
            }
            for item in evidences
        ]

        return {
            "answer": answer,
            "used_profile_evidence": used_evidence,
        }
