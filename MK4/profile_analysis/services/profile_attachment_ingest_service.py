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
from memory.services.memory_ingress_service import MemoryIngressService
from profile_analysis.stores.uploaded_profile_evidence_store import UploadedProfileEvidenceStore
from profile_analysis.stores.uploaded_profile_source_store import UploadedProfileSourceStore
from memory.services.evidence_extraction_service import EvidenceExtractionService
from memory.services.evidence_normalization_service import EvidenceNormalizationService
from memory.services.passage_selection_service import PassageSelectionService
from prompts.prompt_loader import load_prompt_text
from tools.response_runner import ResponseRunner
class ProfileAttachmentIngestService:
    def __init__(self) -> None:
        self.source_store = UploadedProfileSourceStore()
        self.evidence_store = UploadedProfileEvidenceStore()
        self.state_store = StateStore()
        self.extraction_service = EvidenceExtractionService(timeout=120, num_predict=384, retry_num_predict=256)
        self.answer_runner = ResponseRunner(timeout=ATTACHMENT_REPLY_TIMEOUT, num_predict=ATTACHMENT_REPLY_NUM_PREDICT, max_continuations=ATTACHMENT_REPLY_MAX_CONTINUATIONS)
        self.memory_policy = MemoryClassificationPolicy()
        self.passage_selector = PassageSelectionService()
        self.normalizer = EvidenceNormalizationService()
        self.memory_ingress = MemoryIngressService()

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
        max_total_chars: int = 2200,
        max_passages: int = 6,
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

    def _build_head_excerpt_user_prompt(
        self,
        source_id: str,
        filename: str,
        content: str,
        max_total_chars: int = 3200,
    ) -> tuple[str, dict]:
        selected_passages, selection_meta = self.passage_selector.build_head_excerpt_passages(
            filename=filename,
            content=content,
            max_total_chars=max_total_chars,
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
        candidates, _meta = self._extract_json_array_with_meta(text)
        return candidates


    def _extract_json_array_with_meta(self, text: str) -> tuple[list[dict], dict]:
        return self.extraction_service.parse_profile_candidates_with_meta(
            text,
            normalize_source_strength=self.memory_policy.normalize_source_strength,
            include_source_file_paths=False,
        )
    
    def _run_attachment_extract_pipeline(
        self,
        *,
        source_id: str,
        filename: str,
        content: str,
        model: str | None = None,
    ) -> tuple[list[dict], dict, str | None]:
        attempts: list[dict] = []

        primary_prompt, primary_selection_meta = self._build_extract_user_prompt(
            source_id=source_id,
            filename=filename,
            content=content,
            max_total_chars=2200,
            max_passages=6,
        )
        primary_retry_prompt, _ = self._build_extract_user_prompt(
            source_id=source_id,
            filename=filename,
            content=content,
            max_total_chars=1500,
            max_passages=4,
        )
        primary_answer, primary_error = self._run_extract(
            user_prompt=primary_prompt,
            model=model,
            retry_user_prompt=primary_retry_prompt,
        )
        primary_candidates, primary_parse_meta = self._extract_json_array_with_meta(primary_answer)
        attempts.append(
            {
                "attempt": "selected_passages",
                "selection_mode": primary_selection_meta["selection_mode"],
                "selected_passage_count": primary_selection_meta["selected_passage_count"],
                "selected_chars": primary_selection_meta["selected_chars"],
                "candidate_count": len(primary_candidates),
                "parse_status": primary_parse_meta.get("parse_status"),
                "raw_item_count": primary_parse_meta.get("raw_item_count"),
                "dropped_candidate_count": primary_parse_meta.get("dropped_candidate_count"),
                "extract_error": primary_error,
                "answer_preview": (primary_answer or "")[:220],
            }
        )

        if primary_candidates:
            return primary_candidates, {
                "fallback_used": False,
                "final_selection_meta": primary_selection_meta,
                "final_parse_meta": primary_parse_meta,
                "attempts": attempts,
            }, primary_error

        fallback_prompt, fallback_selection_meta = self._build_head_excerpt_user_prompt(
            source_id=source_id,
            filename=filename,
            content=content,
            max_total_chars=3200,
        )
        fallback_answer, fallback_error = self._run_extract(
            user_prompt=fallback_prompt,
            model=model,
            retry_user_prompt=None,
        )
        fallback_candidates, fallback_parse_meta = self._extract_json_array_with_meta(fallback_answer)
        attempts.append(
            {
                "attempt": "head_excerpt_fallback",
                "selection_mode": fallback_selection_meta["selection_mode"],
                "selected_passage_count": fallback_selection_meta["selected_passage_count"],
                "selected_chars": fallback_selection_meta["selected_chars"],
                "candidate_count": len(fallback_candidates),
                "parse_status": fallback_parse_meta.get("parse_status"),
                "raw_item_count": fallback_parse_meta.get("raw_item_count"),
                "dropped_candidate_count": fallback_parse_meta.get("dropped_candidate_count"),
                "extract_error": fallback_error,
                "answer_preview": (fallback_answer or "")[:220],
            }
        )

        final_error = fallback_error or primary_error
        return fallback_candidates, {
            "fallback_used": True,
            "final_selection_meta": fallback_selection_meta,
            "final_parse_meta": fallback_parse_meta,
            "attempts": attempts,
        }, final_error

    def _dedupe_evidence(self, evidences: list[dict]) -> list[dict]:
        seen: set[tuple[str, str]] = set()
        result: list[dict] = []

        sorted_items = sorted(
            evidences,
            key=lambda item: (
                -float(item.get("confidence") or 0.0),
                -SOURCE_STRENGTH_ORDER.get(item.get("source_strength") or "", 0),
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
        text = self.passage_selector.normalize_whitespace(user_request)
        shortened = text[:220].rstrip()
        if len(text) > 220:
            shortened += "..."
        return shortened

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
        request_summary = request_summary or "(요청 요지 없음)"

        evidence_lines = []
        for item in used_evidence[:4]:
            topic = self.passage_selector.normalize_whitespace(str(item.get("topic") or ""))
            candidate = self.passage_selector.normalize_whitespace(str(item.get("candidate_content") or ""))
            strength = self.passage_selector.normalize_whitespace(str(item.get("source_strength") or ""))
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
            f"[요청 요지]\n{request_summary}\n\n"
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

        selected_passages, selection_meta = self.passage_selector.select_followup_passages(
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

        source = self.source_store.add(
            filename=filename,
            content=clean_content,
            user_request=user_request,
        )
        source_id = source["id"]
        self.state_store.set_state('recent_profile_source_id', source_id, source='profile_attachment')
        self.state_store.set_state('recent_profile_source_filename', filename, source='profile_attachment')

        candidates, extract_debug, extract_error = self._run_attachment_extract_pipeline(
            source_id=source_id,
            filename=filename,
            content=clean_content,
            model=model,
        )

        selection_meta = extract_debug["final_selection_meta"]
        parse_meta = extract_debug["final_parse_meta"]

        evidence_envelopes = self.normalizer.normalize_profile_candidate_envelopes(
            candidates,
            channel="uploaded_text",
            include_source_file_paths=False,
        )
        self.memory_ingress.persist_profile_candidate_envelopes(
            channel="uploaded_text",
            owner_id=source_id,
            source_file_path=filename,
            evidence_envelopes=evidence_envelopes,
        )

        sync_result = self.memory_ingress.sync_uploaded_source(source_id)
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
            "fallback_used": bool(extract_debug.get("fallback_used")),
            "parse_status": parse_meta.get("parse_status"),
            "raw_item_count": parse_meta.get("raw_item_count", 0),
            "valid_candidate_count": parse_meta.get("valid_candidate_count", len(candidates)),
            "dropped_candidate_count": parse_meta.get("dropped_candidate_count", 0),
            "attempt_count": len(extract_debug.get("attempts", [])),
            "attempts": extract_debug.get("attempts", []),
            "evidence_envelopes": evidence_envelopes,
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
