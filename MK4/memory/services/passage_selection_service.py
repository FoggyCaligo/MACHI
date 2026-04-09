from __future__ import annotations

import re
from pathlib import Path

from tools.text_embedding import cosine_similarity, embed_text, embed_texts

PROFILE_DOC_EXTENSIONS = {".txt", ".md", ".markdown", ".rst"}
PROFILE_SELECTION_QUERY = (
    "사용자의 비교적 안정적인 특징, 사고 방식, 선호, 반복되는 문제의식, 자기서술이 드러나는 부분"
)


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

    def filter_profile_documents(self, files: list[dict], max_docs: int = 8) -> list[dict]:
        selected: list[dict] = []
        for file in files:
            path = file.get("path") or ""
            ext = (file.get("ext") or Path(path).suffix or "").lower()
            content = (file.get("content") or "").strip()
            if not content:
                continue
            if ext in PROFILE_DOC_EXTENSIONS:
                selected.append({"path": path, "content": content})
        return selected[:max_docs]

    def select_profile_passages(
        self,
        *,
        filename: str,
        content: str,
        max_total_chars: int = 1800,
        max_passages: int = 5,
    ) -> tuple[list[dict], dict]:
        passages = self.split_passages(content)
        return self._rank_passages(
            passages=passages,
            filename=filename,
            query_text=PROFILE_SELECTION_QUERY,
            kind="profile_passages",
            max_total_chars=max_total_chars,
            max_passages=max_passages,
            fallback_content=content,
        )

    def select_followup_passages(
        self,
        *,
        filename: str,
        content: str,
        user_request: str,
        max_total_chars: int = 1600,
        max_passages: int = 4,
    ) -> tuple[list[dict], dict]:
        passages = self.split_passages(content)
        query = self.normalize_whitespace(user_request) or PROFILE_SELECTION_QUERY
        return self._rank_passages(
            passages=passages,
            filename=filename,
            query_text=query,
            kind="recent_source_followup",
            max_total_chars=max_total_chars,
            max_passages=max_passages,
            fallback_content=content,
        )

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
        query_vec = embed_text(PROFILE_SELECTION_QUERY, kind="query")
        for doc in documents:
            filename = doc.get("path") or doc.get("filename") or "__unknown__"
            content = doc.get("content") or ""
            if not content:
                continue
            passages = self.split_passages(content)
            if not passages:
                continue
            document_count += 1
            passage_vecs = embed_texts(passages, kind="passage")
            for index, (passage, vector) in enumerate(zip(passages, passage_vecs), start=1):
                candidates.append(
                    {
                        "filename": filename,
                        "passage_index": index,
                        "score": cosine_similarity(query_vec, vector),
                        "text": passage,
                    }
                )
        candidates.sort(
            key=lambda item: (
                -item["score"],
                -min(len(item["text"]), 700),
                item["filename"],
                item["passage_index"],
            )
        )

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
        if selected:
            return selected, {
                "selected_passage_count": len(selected),
                "selected_chars": total_chars,
                "document_count": document_count,
                "selection_mode": "profile_passages_across_documents",
            }
        return [], {
            "selected_passage_count": 0,
            "selected_chars": 0,
            "document_count": document_count,
            "selection_mode": "profile_passages_across_documents",
        }

    def _rank_passages(
        self,
        *,
        passages: list[str],
        filename: str,
        query_text: str,
        kind: str,
        max_total_chars: int,
        max_passages: int,
        fallback_content: str,
    ) -> tuple[list[dict], dict]:
        if not passages:
            return self._fallback_excerpt(fallback_content, filename, f"{kind}_head_excerpt")

        query_vec = embed_text(query_text, kind="query")
        passage_vecs = embed_texts(passages, kind="passage")
        candidates = []
        for index, (passage, vector) in enumerate(zip(passages, passage_vecs), start=1):
            candidates.append(
                {
                    "filename": filename,
                    "passage_index": index,
                    "score": cosine_similarity(query_vec, vector),
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
            text = self._truncate_to_budget(item["text"], remaining)
            if not text:
                continue
            selected.append({**item, "text": text})
            total_chars += len(text)
        if selected:
            return selected, {
                "selected_passage_count": len(selected),
                "selected_chars": total_chars,
                "selection_mode": kind,
            }
        return self._fallback_excerpt(fallback_content, filename, f"{kind}_head_excerpt")

    def _truncate_to_budget(self, text: str, remaining: int) -> str | None:
        if remaining <= 120:
            return None
        if len(text) <= remaining:
            return text
        if remaining < 180:
            return None
        return text[:remaining].rstrip() + "..."

    def _fallback_excerpt(self, content: str, filename: str, mode: str) -> tuple[list[dict], dict]:
        normalized = self.normalize_whitespace(content)
        excerpt = normalized[:1200].rstrip()
        if len(normalized) > 1200:
            excerpt += "..."
        selected = [{"filename": filename, "passage_index": 1, "score": 0.0, "text": excerpt}] if excerpt else []
        return selected, {
            "selected_passage_count": len(selected),
            "selected_chars": sum(len(item["text"]) for item in selected),
            "selection_mode": mode,
        }
