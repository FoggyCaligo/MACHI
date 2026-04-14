from __future__ import annotations

from memory.services.evidence_extraction_service import EvidenceExtractionService
from memory.services.evidence_normalization_service import EvidenceNormalizationService
from memory.services.memory_ingress_service import MemoryIngressService
from memory.services.passage_selection_service import PassageSelectionService
from memory.services.topic_router import TopicRouter
from prompts.prompt_loader import load_prompt_text
from project_analysis.stores.project_file_store import ProjectFileStore
from project_analysis.stores.project_profile_evidence_store import ProjectProfileEvidenceStore
from tools.response_runner import ResponseRunner
from config import (
    EXTRACT_NUM_PREDICT,
    EXTRACT_RETRY_NUM_PREDICT,
    PROFILE_EXTRACT_TIMEOUT,
    PROJECT_PROFILE_EVIDENCE_ANSWER_SYSTEM_PROMPT_PATH,
    PROJECT_PROFILE_EVIDENCE_EXTRACT_SYSTEM_PROMPT_PATH,
    PROJECT_REPLY_MAX_CONTINUATIONS,
    PROJECT_REPLY_NUM_PREDICT,
    PROJECT_REPLY_TIMEOUT,
)


class ProjectProfileEvidenceService:
    def __init__(self) -> None:
        self.file_store = ProjectFileStore()
        self.evidence_store = ProjectProfileEvidenceStore()
        self.topic_router = TopicRouter()
        self.passage_selection_service = PassageSelectionService()
        self.extraction_service = EvidenceExtractionService(
            timeout=PROFILE_EXTRACT_TIMEOUT,
            num_predict=EXTRACT_NUM_PREDICT,
            retry_num_predict=EXTRACT_RETRY_NUM_PREDICT,
        )
        self.normalizer = EvidenceNormalizationService()
        self.memory_ingress = MemoryIngressService()
        self.answer_runner = ResponseRunner(
            timeout=PROJECT_REPLY_TIMEOUT,
            num_predict=PROJECT_REPLY_NUM_PREDICT,
            max_continuations=PROJECT_REPLY_MAX_CONTINUATIONS,
        )

    def _normalize_text(self, text: str) -> str:
        return " ".join((text or "").strip().lower().split())

    def _normalize_paths(self, source_paths: list[str] | None) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for raw_path in source_paths or []:
            path = str(raw_path or "").replace("\\", "/").strip()
            if not path or path in seen:
                continue
            seen.add(path)
            normalized.append(path)
        return normalized

    def _paths_to_extract(
        self,
        *,
        requested_paths: list[str],
        existing_evidences: list[dict],
        file_hash_by_path: dict[str, str],
        force_refresh: bool,
    ) -> tuple[list[str], list[str]]:
        if force_refresh:
            return list(requested_paths), list(requested_paths)

        evidence_rows_by_path: dict[str, list[dict]] = {path: [] for path in requested_paths}
        for evidence in existing_evidences:
            for path in self._normalize_paths(evidence.get("source_file_paths") or []):
                if path in evidence_rows_by_path:
                    evidence_rows_by_path[path].append(evidence)

        stale_paths: list[str] = []
        missing_paths: list[str] = []
        for path in requested_paths:
            matching_rows = evidence_rows_by_path.get(path) or []
            if not matching_rows:
                missing_paths.append(path)
                continue

            stale = False
            for row in matching_rows:
                row_hashes = row.get("source_file_hashes") or {}
                actual_hash = str(row_hashes.get(path) or "").strip()
                expected_hash = str(file_hash_by_path.get(path) or "").strip()
                if actual_hash != expected_hash:
                    stale = True
                    break
            if stale:
                stale_paths.append(path)

        ordered_paths: list[str] = []
        seen: set[str] = set()
        for path in [*missing_paths, *stale_paths]:
            if path and path not in seen:
                seen.add(path)
                ordered_paths.append(path)
        return ordered_paths, stale_paths

    def _file_hash_by_path(self, documents: list[dict]) -> dict[str, str]:
        result: dict[str, str] = {}
        for doc in documents:
            path = str(doc.get("path") or "").replace("\\", "/").strip()
            if not path:
                continue
            content_hash = str(doc.get("content_hash") or "").strip()
            if not content_hash:
                content_hash = self.file_store.compute_content_hash(str(doc.get("content") or ""))
            result[path] = content_hash
        return result

    def _select_documents(self, project_id: str, source_paths: list[str] | None = None) -> list[dict]:
        files = self.file_store.list_full_by_project(project_id)
        normalized_paths = self._normalize_paths(source_paths)
        if normalized_paths:
            by_path = {str(item.get("path") or "").replace("\\", "/"): item for item in files}
            return [by_path[path] for path in normalized_paths if path in by_path]
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

    def ensure_extracted(
        self,
        project_id: str,
        model: str | None = None,
        *,
        source_paths: list[str] | None = None,
        force_refresh: bool = False,
    ) -> dict:
        documents = self._select_documents(project_id, source_paths=source_paths)
        requested_paths = [str(doc.get("path") or "").replace("\\", "/") for doc in documents]
        if not documents:
            return {
                "stored": False,
                "reused": False,
                "document_count": 0,
                "source_files": [],
                "candidate_count": 0,
                "existing_evidence_count": 0,
                "newly_extracted_paths": [],
                "needs_memory_sync": False,
            }

        existing_evidences = self.evidence_store.list_by_project_paths(project_id, requested_paths)
        file_hash_by_path = self._file_hash_by_path(documents)
        paths_to_extract, stale_paths = self._paths_to_extract(
            requested_paths=requested_paths,
            existing_evidences=existing_evidences,
            file_hash_by_path=file_hash_by_path,
            force_refresh=force_refresh,
        )

        if not paths_to_extract:
            return {
                "stored": False,
                "reused": True,
                "document_count": len(documents),
                "source_files": requested_paths,
                "candidate_count": len(existing_evidences),
                "existing_evidence_count": len(existing_evidences),
                "newly_extracted_paths": [],
                "needs_memory_sync": False,
            }

        return self.extract_and_store(
            project_id,
            model=model,
            source_paths=paths_to_extract,
            force_refresh=force_refresh,
        )

    def extract_and_store(
        self,
        project_id: str,
        model: str | None = None,
        *,
        source_paths: list[str] | None = None,
        force_refresh: bool = False,
    ) -> dict:
        documents = self._select_documents(project_id, source_paths=source_paths)
        selected_paths = [str(doc.get("path") or "").replace("\\", "/") for doc in documents]
        if not documents:
            return {
                "stored": False,
                "reused": False,
                "document_count": 0,
                "source_files": [],
                "candidate_count": 0,
                "existing_evidence_count": 0,
                "newly_extracted_paths": [],
                "needs_memory_sync": False,
            }

        removed_existing_count = 0
        if force_refresh and selected_paths:
            removed_existing_count = self.evidence_store.delete_by_project_paths(project_id, selected_paths)

        file_hash_by_path = self._file_hash_by_path(documents)

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

        evidence_envelopes = self.normalizer.normalize_profile_candidate_envelopes(
            candidates,
            channel="project_artifact",
            include_source_file_paths=True,
        )
        self.memory_ingress.persist_profile_candidate_envelopes(
            channel="project_artifact",
            owner_id=project_id,
            evidence_envelopes=evidence_envelopes,
            source_file_hash_by_path=file_hash_by_path,
        )

        return {
            "stored": True,
            "reused": False,
            "document_count": len(documents),
            "source_files": selected_paths,
            "candidate_count": len(candidates),
            "existing_evidence_count": max(removed_existing_count, 0),
            "newly_extracted_paths": selected_paths,
            "needs_memory_sync": bool(evidence_envelopes),
            "evidence_envelopes": evidence_envelopes,
        }

    def answer_from_project(
        self,
        project_id: str,
        question: str,
        model: str | None = None,
    ) -> dict | None:
        ensure_result = self.ensure_extracted(project_id, model=model)
        if ensure_result.get("needs_memory_sync"):
            self.memory_ingress.sync_project(project_id)

        evidences = self.evidence_store.list_by_project(project_id)
        if not evidences:
            return None

        messages = self._build_answer_messages(question, evidences)
        answer = self.answer_runner.run(messages=messages, model=model)
        return {
            "answer": answer.text,
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
