import re

from config import (
    ATTACHMENT_REPLY_MAX_CONTINUATIONS,
    ATTACHMENT_REPLY_NUM_PREDICT,
    ATTACHMENT_REPLY_TIMEOUT,
    PROFILE_ATTACHMENT_ANSWER_SYSTEM_PROMPT_PATH,
    PROJECT_PROFILE_EVIDENCE_EXTRACT_SYSTEM_PROMPT_PATH,
)
from memory.policies.memory_classification_policy import (
    MemoryClassificationPolicy,
    SOURCE_STRENGTH_ORDER,
)
from memory.stores.state_store import StateStore
from profile_analysis.services.profile_memory_sync_service import ProfileMemorySyncService
from profile_analysis.stores.uploaded_profile_evidence_store import UploadedProfileEvidenceStore
from profile_analysis.stores.uploaded_profile_source_store import UploadedProfileSourceStore
from memory.services.evidence_extraction_service import EvidenceExtractionService
from memory.services.passage_selection_service import PassageSelectionService
from prompts.prompt_loader import load_prompt_text
from tools.response_runner import ResponseRunner


FIRST_PERSON_MARKERS = {
    "나는", "내가", "나의", "저는", "제가", "저의", "i am", "i'm", "my ",
}
PREFERENCE_MARKERS = {
    "좋아", "싫어", "선호", "원한다", "바란다", "중요", "필요", "need",
    "기준", "습관", "성향", "생각", "판단", "prefer", "want", "important",
    "habit", "style",
}
PROFILE_FILENAME_HINTS = {
    "profile", "blog", "essay", "memo", "notes", "retrospective",
    "회고", "블로그", "프로필", "메모", "생각", "기록",
}

class ProfileAttachmentIngestService:
    def __init__(self) -> None:
        self.source_store = UploadedProfileSourceStore()
        self.evidence_store = UploadedProfileEvidenceStore()
        self.sync_service = ProfileMemorySyncService()
        self.state_store = StateStore()
        self.extraction_service = EvidenceExtractionService(timeout=120, num_predict=384, retry_num_predict=256)
        self.answer_runner = ResponseRunner(timeout=ATTACHMENT_REPLY_TIMEOUT, num_predict=ATTACHMENT_REPLY_NUM_PREDICT, max_continuations=ATTACHMENT_REPLY_MAX_CONTINUATIONS)
        self.memory_policy = MemoryClassificationPolicy()
        self.passage_selector = PassageSelectionService()

    def _compact_extract_user_prompt(self, source_id: str, filename: str, selected_passages: list[dict], selection_meta: dict) -> str:
        passage_blocks = []
        for idx, item in enumerate(selected_passages, start=1):
            passage_blocks.append(
                f"[자료 {idx}]\n"
                f"source_id: {source_id}\n"
                f"파일명: {filename}\n"
                f"문단 번호: {item['passage_index']}\n"
                f"본문:\n{item['text']}"
            )

        return (
            f"[source]\nsource_id: {source_id}\nfilename: {filename}\n\n"
            f"[selection]\ncount={selection_meta['selected_passage_count']} chars={selection_meta['selected_chars']} mode={selection_meta['selection_mode']}\n\n"
            f"[passages]\n" + "\n\n".join(passage_blocks)
        )

    def _build_extract_user_prompt(
        self,
        source_id: str,
        filename: str,
        content: str,
        max_total_chars: int = 1800,
        max_passages: int = 5,
    ) -> tuple[str, dict]:
        selected_passages, selection_meta = self.passage_selector.select_profile_passages(
            filename=filename,
            content=content,
            max_total_chars=max_total_chars,
            max_passages=max_passages,
        )
        user_prompt = self._compact_extract_user_prompt(
            source_id=source_id,
            filename=filename,
            selected_passages=selected_passages,
            selection_meta=selection_meta,
        )
        return user_prompt, selection_meta

    def _run_extract(
        self,
        user_prompt: str,
        model: str | None = None,
        retry_user_prompt: str | None = None,
    ) -> tuple[str, str | None]:
        result = self.extraction_service.run_extract(
            system_prompt_path=PROJECT_PROFILE_EVIDENCE_EXTRACT_SYSTEM_PROMPT_PATH,
            user_prompt=user_prompt,
            retry_user_prompt=retry_user_prompt,
            model=model,
            require_complete=True,
        )
        return result.text, result.error

    def _extract_json_array(self, text: str) -> list[dict]:
        return self.extraction_service.parse_profile_candidates(
            text,
            normalize_source_strength=self.memory_policy.normalize_source_strength,
            include_source_file_paths=False,
        )

    def _dedupe_evidence(self, evidences: list[dict]) -> list[dict]:
        seen: set[tuple[str, str]] = set()
        result: list[dict] = []

        sorted_items = sorted(
            evidences,
            key=lambda item: (
                -float(item.get("confidence") or 0.0),
                -SOURCE_STRENGTH_ORDER.get(item.get("source_strength") or "repeated_behavior", 0),
                str(item.get("topic") or ""),
            ),
        )

        for item in sorted_items:
            key = (
                str(item.get("topic") or "").strip().lower(),
                str(item.get("candidate_content") or "").strip().lower(),
            )
            if not key[0] or not key[1] or key in seen:
                continue
            seen.add(key)
            result.append(item)

        return result

    def _summarize_user_request(self, user_request: str, filename: str) -> str:
        text = self._normalize_whitespace(user_request)
        if not text:
            return "사용자는 첨부한 텍스트가 프로필 이해와 기억 업데이트에 실제로 도움이 되는지 묻고 있다."

        request_lower = text.lower()
        filename = filename or "첨부 텍스트"

        if ("기억" in text and ("못" in text or "안난" in text or "안 나" in text)) and ("이해" in text or "파악" in text):
            return (
                f"사용자는 내가 이전에 공유된 내용을 정확히 떠올리지 못하더라도, 첨부한 '{filename}'를 바탕으로 "
                "다시 자신에 대한 이해를 시도해줄 수 있는지 묻고 있다."
            )

        if ("도움" in text or "도움이" in text) and ("이해" in text or "파악" in text):
            return (
                f"사용자는 첨부한 '{filename}' 같은 글 묶음이 자신의 성향과 사고 기준을 더 잘 이해하는 데 실제로 도움이 되는지 확인하려 한다."
            )

        if "업데이트" in request_lower or "기억시스템" in text or "기억 시스템" in text:
            return (
                f"사용자는 첨부한 '{filename}'를 기억 시스템의 프로필 근거로 반영해도 되는지, 그리고 이를 바탕으로 자신을 더 입체적으로 이해할 수 있는지 묻고 있다."
            )

        shortened = text[:180].rstrip()
        if len(text) > 180:
            shortened += "..."
        return f"사용자 요청 요지: {shortened}"

    def _build_answer_messages(
        self,
        filename: str,
        user_request: str,
        used_evidence: list[dict],
        sync_result: dict,
        extract_result: dict,
        extract_error: str | None = None,
    ) -> list[dict]:
        system_prompt = load_prompt_text(PROFILE_ATTACHMENT_ANSWER_SYSTEM_PROMPT_PATH)

        request_summary = self._summarize_user_request(user_request=user_request, filename=filename)

        evidence_lines = []
        for item in used_evidence[:4]:
            topic = self._normalize_whitespace(str(item.get("topic") or ""))
            candidate = self._normalize_whitespace(str(item.get("candidate_content") or ""))
            strength = self._normalize_whitespace(str(item.get("source_strength") or ""))
            confidence = item.get("confidence")
            if topic and candidate:
                evidence_lines.append(
                    f"- topic={topic} | candidate={candidate} | strength={strength or '-'} | confidence={confidence}"
                )

        evidence_text = "\n".join(evidence_lines).strip() or "- 강하게 잡힌 evidence 없음"

        promoted = int(sync_result.get("promoted_profiles", 0) or 0)
        linked = int(sync_result.get("linked_existing_profiles", 0) or 0) + int(
            sync_result.get("linked_to_existing_active_profile", 0) or 0
        )
        blocked = int(sync_result.get("blocked_by_correction", 0) or 0) + int(
            sync_result.get("blocked_by_existing_profile_conflict", 0) or 0
        )
        candidate_count = int(extract_result.get("candidate_count", 0) or 0)

        status_summary = (
            f"candidate_count={candidate_count}, linked={linked}, promoted={promoted}, blocked={blocked}"
        )
        if extract_error:
            status_summary += f", extract_error={extract_error[:120]}"

        user_prompt = (
            f"[사용자 요청 요지]\n{request_summary}\n\n"
            f"[핵심 evidence]\n{evidence_text}\n\n"
            f"[반영 상태]\n{status_summary}\n\n"
            "[답변 지침]\n"
            "- 자연스럽게 설명할 것\n"
            "- 존댓말만 사용할 것\n"
            "- 질문 문장을 거의 그대로 반복하지 말 것\n"
            "- 필요한 핵심은 충분히 설명하되, 내부 처리 수치나 파일 정보는 길게 나열하지 말 것\n"
            "- evidence가 거의 없으면 억지로 의미를 부풀리지 말 것"
        )

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    def get_recent_source_id(self) -> str | None:
        row = self.state_store.get_state('recent_profile_source_id')
        value = (row or {}).get('value')
        return str(value).strip() or None

    def build_followup_reference(self, source_id: str, user_request: str) -> dict | None:
        source = self.source_store.get(source_id)
        if not source:
            return None

        selected_passages, selection_meta = self._select_followup_passages(
            filename=str(source.get('filename') or ''),
            content=str(source.get('content') or ''),
            user_request=user_request,
            max_total_chars=1600,
            max_passages=4,
        )
        excerpt = "\n\n".join(item['text'] for item in selected_passages if item.get('text')).strip()
        if not excerpt:
            return None
        return {
            'source_id': source_id,
            'filename': str(source.get('filename') or ''),
            'excerpt': excerpt,
            'selection_meta': selection_meta,
        }

    def ingest_text(
        self,
        filename: str,
        content: str,
        user_request: str,
        model: str | None = None,
    ) -> dict:
        clean_content = (content or "").strip()
        if not clean_content:
            return {
                "answer": "첨부 텍스트가 비어 있어서 프로필 evidence로 반영할 수 없었어.",
                "source_id": None,
                "profile_evidence_extract": {
                    "stored": False,
                    "document_count": 0,
                    "candidate_count": 0,
                    "selected_passage_count": 0,
                    "selected_chars": 0,
                    "selection_mode": "none",
                    "source_files": [],
                },
                "profile_memory_sync": None,
                "used_profile_evidence": [],
            }

        source = self.source_store.add(
            filename=filename,
            content=clean_content,
            user_request=user_request,
        )
        source_id = source["id"]
        self.state_store.set_state('recent_profile_source_id', source_id, source='profile_attachment')
        self.state_store.set_state('recent_profile_source_filename', filename, source='profile_attachment')

        self.evidence_store.delete_by_source(source_id)
        messages, selection_meta = self._build_extract_messages(
            source_id=source_id,
            filename=filename,
            content=clean_content,
            max_total_chars=1800,
            max_passages=5,
        )
        retry_messages, retry_selection_meta = self._build_extract_messages(
            source_id=source_id,
            filename=filename,
            content=clean_content,
            max_total_chars=1100,
            max_passages=3,
        )
        answer, extract_error = self._run_extract(
            messages=messages,
            model=model,
            retry_messages=retry_messages,
        )
        if answer:
            candidates = self._extract_json_array(answer)
        else:
            candidates = []
            selection_meta = retry_selection_meta

        for candidate in candidates:
            self.evidence_store.add(
                source_id=source_id,
                source_file_path=filename,
                evidence_type="profile_candidate",
                topic=candidate["topic"],
                candidate_content=candidate["candidate_content"],
                source_strength=candidate["source_strength"],
                evidence_text=candidate["evidence_text"],
                confidence=candidate["confidence"],
            )

        sync_result = self.sync_service.sync_uploaded_source(source_id)
        stored_evidence = self.evidence_store.list_by_source(source_id)
        used_profile_evidence = [
            {
                "topic": item.get("topic"),
                "source_file_path": item.get("source_file_path"),
                "confidence": item.get("confidence"),
                "source_strength": item.get("source_strength"),
                "candidate_content": item.get("candidate_content"),
            }
            for item in self._dedupe_evidence(stored_evidence)
        ]

        extract_result = {
            "stored": True,
            "document_count": 1,
            "candidate_count": len(candidates),
            "selected_passage_count": selection_meta["selected_passage_count"],
            "selected_chars": selection_meta["selected_chars"],
            "selection_mode": selection_meta["selection_mode"],
            "source_files": [filename],
            "extract_error": extract_error,
        }

        answer_messages = self._build_answer_messages(
            filename=filename,
            user_request=user_request,
            used_evidence=used_profile_evidence,
            sync_result=sync_result,
            extract_result=extract_result,
            extract_error=extract_error,
        )
        user_answer = self.answer_runner.run(
            answer_messages,
            model=model,
        ).text

        return {
            "answer": user_answer,
            "source_id": source_id,
            "profile_evidence_extract": extract_result,
            "profile_memory_sync": sync_result,
            "used_profile_evidence": used_profile_evidence,
        }
