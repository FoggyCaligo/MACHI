from memory.services.evidence_extraction_service import EvidenceExtractionService
from memory.services.passage_selection_service import PassageSelectionService
from memory.services.topic_router import TopicRouter
from prompts.prompt_loader import load_prompt_text
from project_analysis.stores.project_file_store import ProjectFileStore
from project_analysis.stores.project_profile_evidence_store import (
    ProjectProfileEvidenceStore,
)
from tools.response_runner import ResponseRunner
from config import (
    PROJECT_REPLY_MAX_CONTINUATIONS,
    PROJECT_REPLY_NUM_PREDICT,
    PROJECT_REPLY_TIMEOUT,
    PROJECT_PROFILE_EVIDENCE_ANSWER_SYSTEM_PROMPT_PATH,
    PROJECT_PROFILE_EVIDENCE_EXTRACT_SYSTEM_PROMPT_PATH,
)


class ProjectProfileEvidenceService:
    def __init__(self) -> None:
        self.file_store = ProjectFileStore()
        self.evidence_store = ProjectProfileEvidenceStore()
        self.topic_router = TopicRouter()
        self.passage_selection_service = PassageSelectionService()
        self.extraction_service = EvidenceExtractionService(
            timeout=120,
            num_predict=384,
            retry_num_predict=256,
        )
        self.answer_runner = ResponseRunner(
            timeout=PROJECT_REPLY_TIMEOUT,
            num_predict=PROJECT_REPLY_NUM_PREDICT,
            max_continuations=PROJECT_REPLY_MAX_CONTINUATIONS,
        )

    def _select_documents(self, project_id: str) -> list[dict]:
        files = self.file_store.list_full_by_project(project_id)
        return self.passage_selection_service.filter_profile_documents(files, max_docs=8)

    def _build_extract_user_prompt(
        self,
        project_id: str,
        documents: list[dict],
        *,
        max_docs: int = 8,
        max_chars_per_doc: int = 3500,
    ) -> str:
        blocks = []
        for idx, doc in enumerate(documents[:max_docs], start=1):
            content = doc["content"]
            if len(content) > max_chars_per_doc:
                content = content[:max_chars_per_doc].rstrip() + "\n..."

            blocks.append(
                f"[자료 {idx}]\n"
                f"프로젝트: {project_id}\n"
                f"경로: {doc['path']}\n"
                f"본문:\n{content}"
            )

        return "[분석 자료]\n" + "\n\n".join(blocks)

    def _build_answer_messages(self, question: str, evidences: list[dict]) -> list[dict]:
        system_prompt = load_prompt_text(PROJECT_PROFILE_EVIDENCE_ANSWER_SYSTEM_PROMPT_PATH)

        blocks = []
        for idx, evidence in enumerate(evidences, start=1):
            text = (evidence.get("evidence_text") or "").strip()
            if len(text) > 1500:
                text = text[:1500].rstrip() + "\n..."

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

    def _normalize_source_strength(self, value: str | None) -> str:
        normalized = " ".join((value or "").strip().lower().split())
        if normalized in {"explicit_self_statement", "repeated_behavior", "temporary_interest"}:
            return normalized
        return ""

    def _extract_json_array(self, text: str) -> list[dict]:
        result = self.extraction_service.parse_profile_candidates(
            text,
            normalize_source_strength=self._normalize_source_strength,
            include_source_file_paths=True,
        )

        for item in result:
            item["source_strength"] = self._normalize_source_strength(item.get("source_strength"))

        return result

    def _resolve_candidate_topic(self, candidate: dict, model: str | None = None) -> dict:
        candidate_content = self._normalize_text(str(candidate.get("candidate_content") or ""))
        raw_topic = self._normalize_text(str(candidate.get("topic") or ""))
        evidence_text = self._normalize_text(str(candidate.get("evidence_text") or ""))

        routing_text = candidate_content
        if raw_topic:
            routing_text = f"{routing_text}\n{raw_topic}".strip()
        if evidence_text:
            routing_text = f"{routing_text}\n{evidence_text[:280]}".strip()

        resolution = self.topic_router.resolve(
            user_message=routing_text,
            model=model,
            use_active_topic=False,
            persist_active=False,
        )

        routed = dict(candidate)
        routed["topic_id"] = resolution.topic_id
        routed["topic"] = resolution.topic_summary or raw_topic or "general"
        routed["topic_resolution"] = {
            "decision": resolution.decision,
            "similarity": resolution.similarity,
        }
        return routed

    def _normalize_text(self, text: str) -> str:
        return " ".join((text or "").strip().lower().split())

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

        user_prompt = self._build_extract_user_prompt(
            project_id=project_id,
            documents=documents,
            max_docs=8,
            max_chars_per_doc=3000,
        )
        retry_user_prompt = self._build_extract_user_prompt(
            project_id=project_id,
            documents=documents,
            max_docs=4,
            max_chars_per_doc=1600,
        )
        extract_result = self.extraction_service.run_extract(
            system_prompt_path=PROJECT_PROFILE_EVIDENCE_EXTRACT_SYSTEM_PROMPT_PATH,
            user_prompt=user_prompt,
            retry_user_prompt=retry_user_prompt,
            model=model,
            require_complete=True,
        )
        candidates = [
            self._resolve_candidate_topic(candidate, model=model)
            for candidate in self._extract_json_array(extract_result.text)
        ]

        for candidate in candidates:
            source_paths = candidate.get("source_file_paths") or []
            source_file_path = ", ".join(source_paths) if source_paths else "__unknown__"

            self.evidence_store.add(
                project_id=project_id,
                source_file_path=source_file_path,
                evidence_type="profile_candidate",
                topic=candidate["topic"],
                topic_id=candidate.get("topic_id"),
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

    def answer_from_project(
        self,
        project_id: str,
        question: str,
        model: str | None = None,
    ) -> dict | None:
        evidences = self.evidence_store.list_by_project(project_id)
        if not evidences:
            self.extract_and_store(project_id, model=model)
            evidences = self.evidence_store.list_by_project(project_id)

        if not evidences:
            return None

        messages = self._build_answer_messages(question, evidences)
        answer = self.answer_runner.run(messages=messages, model=model)
        return {
            "answer": answer,
            "used_profile_evidence": [
                {
                    "topic": evidence.get("topic"),
                    "topic_id": evidence.get("topic_id"),
                    "candidate_content": evidence.get("candidate_content"),
                    "source_file_path": evidence.get("source_file_path"),
                    "confidence": evidence.get("confidence"),
                }
                for evidence in evidences[:8]
            ],
        }
