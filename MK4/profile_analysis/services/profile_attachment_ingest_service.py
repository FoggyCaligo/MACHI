import json
import re

from config import PROJECT_PROFILE_EVIDENCE_EXTRACT_SYSTEM_PROMPT_PATH
from profile_analysis.services.profile_memory_sync_service import ProfileMemorySyncService
from profile_analysis.stores.uploaded_profile_evidence_store import UploadedProfileEvidenceStore
from profile_analysis.stores.uploaded_profile_source_store import UploadedProfileSourceStore
from prompts.prompt_loader import load_prompt_text
from tools.ollama_client import OllamaClient


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
SOURCE_STRENGTH_ORDER = {
    "temporary_interest": 1,
    "repeated_behavior": 2,
    "explicit_self_statement": 3,
}


class ProfileAttachmentIngestService:
    def __init__(self) -> None:
        self.source_store = UploadedProfileSourceStore()
        self.evidence_store = UploadedProfileEvidenceStore()
        self.sync_service = ProfileMemorySyncService()
        self.extract_client = OllamaClient(timeout=150, num_predict=640)

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

    def _score_passage(self, passage: str, filename: str) -> int:
        lowered = passage.lower()
        path_lower = (filename or "").lower()
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
        filename: str,
        content: str,
        max_total_chars: int = 2600,
        max_passages: int = 8,
    ) -> tuple[list[dict], dict]:
        passages = self._split_passages(content)
        candidates: list[dict] = []

        for index, passage in enumerate(passages, start=1):
            candidates.append(
                {
                    "filename": filename,
                    "passage_index": index,
                    "score": self._score_passage(passage, filename),
                    "text": passage,
                }
            )

        candidates.sort(
            key=lambda item: (
                -item["score"],
                -min(len(item["text"]), 700),
                item["passage_index"],
            )
        )

        selected: list[dict] = []
        total_chars = 0
        for item in candidates:
            if len(selected) >= max_passages:
                break

            remaining = max_total_chars - total_chars
            if remaining <= 120:
                break

            text = item["text"]
            if len(text) > remaining:
                if remaining < 180:
                    continue
                text = text[:remaining].rstrip() + "..."

            selected.append(
                {
                    "filename": item["filename"],
                    "passage_index": item["passage_index"],
                    "score": item["score"],
                    "text": text,
                }
            )
            total_chars += len(text)

        if selected:
            return selected, {
                "selected_passage_count": len(selected),
                "selected_chars": total_chars,
                "selection_mode": "self_referential_passages",
            }

        excerpt = self._normalize_whitespace(content)[:1200].rstrip()
        if len(content) > 1200:
            excerpt += "..."

        fallback = [{
            "filename": filename,
            "passage_index": 1,
            "score": 0,
            "text": excerpt,
        }]
        return fallback, {
            "selected_passage_count": 1 if excerpt else 0,
            "selected_chars": len(excerpt),
            "selection_mode": "fallback_head_excerpt",
        }

    def _build_extract_messages(self, source_id: str, filename: str, content: str) -> tuple[list[dict], dict]:
        system_prompt = load_prompt_text(PROJECT_PROFILE_EVIDENCE_EXTRACT_SYSTEM_PROMPT_PATH)
        selected_passages, selection_meta = self._select_relevant_passages(filename=filename, content=content)

        passage_blocks = []
        for idx, item in enumerate(selected_passages, start=1):
            passage_blocks.append(
                f"[자료 {idx}]\n"
                f"source_id: {source_id}\n"
                f"파일명: {filename}\n"
                f"문단 번호: {item['passage_index']}\n"
                f"선별 점수: {item['score']}\n"
                f"본문:\n{item['text']}"
            )

        user_prompt = (
            f"[업로드 source]\nsource_id: {source_id}\n파일명: {filename}\n\n"
            f"[선별 정보]\n"
            f"- selected_passage_count: {selection_meta['selected_passage_count']}\n"
            f"- selected_chars: {selection_meta['selected_chars']}\n"
            f"- selection_mode: {selection_meta['selection_mode']}\n\n"
            f"[분석 자료]\n" + "\n\n".join(passage_blocks)
        )

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ], selection_meta

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
                }
            )

        return result

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

    def _build_user_reply(
        self,
        filename: str,
        used_evidence: list[dict],
        sync_result: dict,
    ) -> str:
        stable_candidates = [
            item for item in used_evidence
            if (item.get("source_strength") or "") != "temporary_interest"
        ]
        top_candidates = stable_candidates[:2]

        lines: list[str] = [
            "응, 이런 글 묶음은 일반 대화만 있을 때보다 나를 파악하는 데 확실히 더 도움이 돼. "
            "대화에서는 순간 반응이 많이 보이지만, 글에서는 네가 무엇을 중요하게 보는지와 어떤 기준으로 생각을 정리하는지가 더 길게 드러나기 때문이야.",
        ]

        if top_candidates:
            candidate_bits = []
            for item in top_candidates:
                candidate = str(item.get("candidate_content") or "").strip()
                topic = str(item.get("topic") or "").strip()
                if topic and candidate:
                    candidate_bits.append(f"{topic}: {candidate}")
                elif candidate:
                    candidate_bits.append(candidate)

            lines.append(
                "이번 텍스트에서는 특히 "
                + "; ".join(candidate_bits)
                + " 쪽이 반복 패턴 후보로 잡혔어. "
                  "다만 이걸 곧바로 확정 성향으로 박아두진 않고, 다른 자료에서도 같은 방향이 반복되는지 보면서 보수적으로 반영하는 게 맞아."
            )
        else:
            lines.append(
                "이번 텍스트도 내부 근거로는 저장했지만, 지금 당장 강하게 잡히는 반복 패턴은 많지 않았어. "
                "그래도 이후 자료와 합쳐 보면 의미가 생길 수 있어서 일단 evidence로는 남겨두는 쪽이 좋아."
            )

        promoted = int(sync_result.get("promoted_profiles") or 0)
        linked = int(sync_result.get("linked_existing_profiles") or 0) + int(sync_result.get("linked_to_existing_active_profile") or 0)
        blocked = int(sync_result.get("blocked_by_correction") or 0) + int(sync_result.get("blocked_by_existing_profile_conflict") or 0)

        lines.append(
            f"이번 업로드는 내부적으로 프로필 evidence로 저장했고, "
            f"기존 기억과의 연결 {linked}건, 새 승격 {promoted}건, 보류/충돌 {blocked}건으로 처리했어. "
            f"파일명은 {filename} 기준으로 묶여 있어서 나중에 다시 추적도 가능해."
        )

        lines.append(
            "한 줄로 말하면, 이런 텍스트 파일은 분명 도움이 되고, 특히 네 사고 기준이나 불편함의 방향 같은 건 일반 잡담보다 훨씬 잘 드러나. "
            "다만 한 번의 글 묶음만으로 단정하지 않고, 반복성과 충돌 여부를 같이 보면서 업데이트할게."
        )
        return "\n\n".join(lines)

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

        self.evidence_store.delete_by_source(source_id)
        messages, selection_meta = self._build_extract_messages(
            source_id=source_id,
            filename=filename,
            content=clean_content,
        )
        answer = self.extract_client.chat(
            messages,
            model=model,
            require_complete=True,
            truncated_notice=None,
        ).strip()
        candidates = self._extract_json_array(answer)

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

        user_answer = self._build_user_reply(
            filename=filename,
            used_evidence=used_profile_evidence,
            sync_result=sync_result,
        )

        return {
            "answer": user_answer,
            "source_id": source_id,
            "profile_evidence_extract": {
                "stored": True,
                "document_count": 1,
                "candidate_count": len(candidates),
                "selected_passage_count": selection_meta["selected_passage_count"],
                "selected_chars": selection_meta["selected_chars"],
                "selection_mode": selection_meta["selection_mode"],
                "source_files": [filename],
            },
            "profile_memory_sync": sync_result,
            "used_profile_evidence": used_profile_evidence,
        }
