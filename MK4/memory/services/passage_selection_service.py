from __future__ import annotations

import re
from pathlib import Path

from memory.constants.language_signals import FIRST_PERSON_MARKERS, PREFERENCE_MARKERS

PROFILE_DOC_EXTENSIONS = {".txt", ".md", ".markdown", ".rst"}
PROFILE_NAME_HINTS = {
    "readme.md",
    "readme.txt",
    "about.md",
    "profile.md",
    "notes.md",
    "plan.md",
    "planning.md",
    "retrospective.md",
}
GENERIC_STOPWORDS = {
    '그리고', '그러면', '그러니까', '이거', '그거', '그것', '이것', '저것', '질문', '답변',
    '파일', '첨부', '내용', '기억', '말해줘', '알려줘', '있니', '뭐였지',
}


class PassageSelectionService:
    def normalize_whitespace(self, text: str) -> str:
        return re.sub(r"\s+", " ", (text or "")).strip()

    def split_passages(self, content: str) -> list[str]:
        raw_parts = re.split(r"\n\s*\n+", content)
        parts = [self.normalize_whitespace(part) for part in raw_parts]
        parts = [part for part in parts if len(part) >= 40]
        if parts:
            return parts

        lines = [self.normalize_whitespace(line) for line in content.splitlines()]
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

    def extract_query_terms(self, user_request: str) -> list[str]:
        text = (user_request or '').lower()
        terms = re.findall(r"[a-zA-Z]{2,}|[가-힣]{2,}", text)
        seen = set()
        ordered: list[str] = []
        for term in terms:
            if term in GENERIC_STOPWORDS:
                continue
            if term not in seen:
                seen.add(term)
                ordered.append(term)
        return ordered[:10]

    def score_profile_passage(self, passage: str, filename: str) -> int:
        lowered = passage.lower()
        path_lower = (filename or "").lower()
        score = 0
        for marker in FIRST_PERSON_MARKERS:
            if marker in lowered:
                score += 3
        for marker in PREFERENCE_MARKERS:
            if marker in lowered:
                score += 2
        if len(passage) >= 250:
            score += 1
        if len(passage) >= 500:
            score += 1
        return score

    def score_followup_passage(self, passage: str, filename: str, user_request: str, passage_index: int) -> int:
        score = self.score_profile_passage(passage, filename)
        lowered = passage.lower()
        for term in self.extract_query_terms(user_request):
            if term in lowered:
                score += 4
        if any(token in user_request for token in ('첫번째', '첫 번째', '처음', '맨 처음', '첫 글')):
            score += max(0, 6 - min(passage_index, 6))
        return score

    def filter_profile_documents(self, files: list[dict], max_docs: int = 8) -> list[dict]:
        selected: list[dict] = []
        for file in files:
            path = file.get("path") or ""
            ext = (file.get("ext") or "").lower()
            name = Path(path).name.lower()
            content = (file.get("content") or "").strip()
            if not content:
                continue
            if ext in PROFILE_DOC_EXTENSIONS or name in PROFILE_NAME_HINTS:
                selected.append({"path": path, "content": content})
        return selected[:max_docs]

    def select_profile_passages(self, *, filename: str, content: str, max_total_chars: int = 1800, max_passages: int = 5) -> tuple[list[dict], dict]:
        candidates = [
            {
                "filename": filename,
                "passage_index": index,
                "score": self.score_profile_passage(passage, filename),
                "text": passage,
            }
            for index, passage in enumerate(self.split_passages(content), start=1)
        ]
        candidates.sort(key=lambda item: (-item["score"], -min(len(item["text"]), 700), item["passage_index"]))
        return self._select_ranked_candidates(
            candidates,
            max_total_chars=max_total_chars,
            max_passages=max_passages,
            selected_mode="self_referential_passages",
            fallback_mode="fallback_head_excerpt",
            fallback_content=content,
            fallback_filename=filename,
        )

    def select_followup_passages(self, *, filename: str, content: str, user_request: str, max_total_chars: int = 1600, max_passages: int = 4) -> tuple[list[dict], dict]:
        passages = self.split_passages(content)
        candidates = [
            {
                "filename": filename,
                "passage_index": index,
                "score": self.score_followup_passage(passage, filename, user_request, index),
                "text": passage,
            }
            for index, passage in enumerate(passages, start=1)
        ]
        candidates.sort(key=lambda item: (-item["score"], item["passage_index"]))

        selected: list[dict] = []
        total_chars = 0
        seen_index: set[int] = set()
        if passages:
            head = self.normalize_whitespace(passages[0])[:500].rstrip()
            if head:
                if len(head) < len(passages[0][:500].rstrip()):
                    head += "..."
                selected.append({"filename": filename, "passage_index": 1, "score": 0, "text": head})
                total_chars += len(head)
                seen_index.add(1)
        for item in candidates:
            if len(selected) >= max_passages:
                break
            if item["passage_index"] in seen_index:
                continue
            remaining = max_total_chars - total_chars
            text = self._truncate_to_budget(item["text"], remaining)
            if not text:
                continue
            selected.append({**item, "text": text})
            total_chars += len(text)
            seen_index.add(item["passage_index"])
        if selected:
            return selected, {
                "selected_passage_count": len(selected),
                "selected_chars": total_chars,
                "selection_mode": "recent_source_followup",
            }
        return self._fallback_excerpt(content, filename, "recent_source_head_excerpt")

    def select_profile_passages_across_documents(
        self,
        *,
        documents: list[dict],
        max_total_chars: int = 2800,
        max_passages: int = 8,
        max_chars_per_doc: int = 900,
    ) -> tuple[list[dict], dict]:
        candidates: list[dict] = []
        document_count = 0
        for doc in documents:
            filename = doc.get("path") or doc.get("filename") or "__unknown__"
            content = doc.get("content") or ""
            if not content:
                continue
            document_count += 1
            for index, passage in enumerate(self.split_passages(content), start=1):
                candidates.append({
                    "filename": filename,
                    "passage_index": index,
                    "score": self.score_profile_passage(passage, filename),
                    "text": passage,
                })
        candidates.sort(key=lambda item: (-item["score"], -min(len(item["text"]), 700), item["filename"], item["passage_index"]))

        selected: list[dict] = []
        total_chars = 0
        per_doc_used: dict[str, int] = {}
        for item in candidates:
            if len(selected) >= max_passages:
                break
            remaining = max_total_chars - total_chars
            if remaining <= 120:
                break
            used = per_doc_used.get(item["filename"], 0)
            if used >= max_chars_per_doc:
                continue
            doc_budget = min(remaining, max_chars_per_doc - used)
            text = self._truncate_to_budget(item["text"], doc_budget)
            if not text:
                continue
            selected.append({**item, "text": text})
            total_chars += len(text)
            per_doc_used[item["filename"]] = used + len(text)
        return selected, {
            "selected_passage_count": len(selected),
            "selected_chars": total_chars,
            "document_count": document_count,
            "selection_mode": "profile_passages_across_documents",
        }

    def _select_ranked_candidates(
        self,
        candidates: list[dict],
        *,
        max_total_chars: int,
        max_passages: int,
        selected_mode: str,
        fallback_mode: str,
        fallback_content: str,
        fallback_filename: str,
    ) -> tuple[list[dict], dict]:
        selected: list[dict] = []
        total_chars = 0
        for item in candidates:
            if len(selected) >= max_passages:
                break
            remaining = max_total_chars - total_chars
            text = self._truncate_to_budget(item["text"], remaining)
            if not text:
                continue
            selected.append({**item, "text": text})
            total_chars += len(text)
        if selected:
            return selected, {
                "selected_passage_count": len(selected),
                "selected_chars": total_chars,
                "selection_mode": selected_mode,
            }
        return self._fallback_excerpt(fallback_content, fallback_filename, fallback_mode)

    def _truncate_to_budget(self, text: str, remaining: int) -> str | None:
        if remaining <= 120:
            return None
        if len(text) <= remaining:
            return text
        if remaining < 180:
            return None
        return text[:remaining].rstrip() + "..."

    def _fallback_excerpt(self, content: str, filename: str, mode: str) -> tuple[list[dict], dict]:
        excerpt = self.normalize_whitespace(content)[:1200].rstrip()
        if len(content) > 1200:
            excerpt += "..."
        return [{"filename": filename, "passage_index": 1, "score": 0, "text": excerpt}], {
            "selected_passage_count": 1 if excerpt else 0,
            "selected_chars": len(excerpt),
            "selection_mode": mode,
        }
