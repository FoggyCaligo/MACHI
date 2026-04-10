from __future__ import annotations

import re
from typing import Iterable

from tools.text_embedding import cosine_similarity, embed_text, embed_texts

PROFILE_SELECTION_QUERY = (
    "사용자의 비교적 안정적인 특징, 사고 방식, 설명 선호, 반복되는 기준, "
    "정서적 반응 패턴, 의사결정 방식, 교정이 필요한 해석 축을 잘 보여주는 문단"
)
PROFILE_DOC_QUERY = (
    "사용자 프로필 형성에 도움이 되는 문서. 사용자의 특징, 사고 방식, 선호, "
    "반복되는 관심사나 기준이 드러난 문서"
)


class PassageSelectionService:
    def normalize_whitespace(self, text: str) -> str:
        return re.sub(r"\s+", " ", (text or "")).strip()

    def split_passages(self, content: str) -> list[str]:
        raw_parts = re.split(r"\n\s*\n+", content or "")
        parts = [self.normalize_whitespace(part) for part in raw_parts]
        parts = [part for part in parts if len(part) >= 40]
        if parts:
            return parts

        lines = [self.normalize_whitespace(line) for line in (content or "").splitlines()]
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
        candidates: list[dict] = []
        for file in files:
            path = file.get("path") or file.get("filename") or "__unknown__"
            content = (file.get("content") or "").strip()
            if not content:
                continue
            excerpt = self.normalize_whitespace(content)[:1600]
            candidates.append({
                "path": path,
                "content": content,
                "excerpt": excerpt,
            })
        if not candidates:
            return []

        query_embedding = embed_text(PROFILE_DOC_QUERY, kind="query")
        passage_embeddings = embed_texts([item["excerpt"] for item in candidates], kind="passage")
        ranked: list[tuple[float, dict]] = []
        for item, emb in zip(candidates, passage_embeddings):
            ranked.append((cosine_similarity(query_embedding, emb), item))
        ranked.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _, item in ranked[:max_docs]]

    def select_profile_passages(
        self,
        *,
        filename: str,
        content: str,
        max_total_chars: int = 1800,
        max_passages: int = 5,
    ) -> tuple[list[dict], dict]:
        return self._rank_single_document(
            filename=filename,
            content=content,
            query=PROFILE_SELECTION_QUERY,
            max_total_chars=max_total_chars,
            max_passages=max_passages,
            selection_mode="profile_passage_embedding_similarity",
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
        query = self.normalize_whitespace(user_request)
        if not query:
            query = PROFILE_SELECTION_QUERY
        return self._rank_single_document(
            filename=filename,
            content=content,
            query=query,
            max_total_chars=max_total_chars,
            max_passages=max_passages,
            selection_mode="followup_passage_embedding_similarity",
        )

    def select_profile_passages_across_documents(
        self,
        *,
        documents: list[dict],
        max_total_chars: int = 2800,
        max_passages: int = 8,
        max_chars_per_doc: int = 900,
    ) -> tuple[list[dict], dict]:
        query_embedding = embed_text(PROFILE_SELECTION_QUERY, kind="query")
        document_count = 0
        candidates: list[dict] = []
        texts: list[str] = []

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
                    "text": passage,
                })
                texts.append(passage)

        if not candidates:
            return [], {
                "selected_passage_count": 0,
                "selected_chars": 0,
                "document_count": 0,
                "selection_mode": "none",
            }

        embeddings = embed_texts(texts, kind="passage")
        ranked: list[dict] = []
        for item, emb in zip(candidates, embeddings):
            ranked.append({
                **item,
                "score": cosine_similarity(query_embedding, emb),
            })
        ranked.sort(key=lambda item: (-item["score"], item["filename"], item["passage_index"]))

        selected: list[dict] = []
        total_chars = 0
        per_doc_used: dict[str, int] = {}
        for item in ranked:
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
            "selection_mode": "profile_passages_across_documents_embedding_similarity",
        }

    def _rank_single_document(
        self,
        *,
        filename: str,
        content: str,
        query: str,
        max_total_chars: int,
        max_passages: int,
        selection_mode: str,
    ) -> tuple[list[dict], dict]:
        passages = self.split_passages(content)
        if not passages:
            return [], {
                "selected_passage_count": 0,
                "selected_chars": 0,
                "selection_mode": "none",
            }

        query_embedding = embed_text(query, kind="query")
        passage_embeddings = embed_texts(passages, kind="passage")
        ranked: list[dict] = []
        for index, (passage, emb) in enumerate(zip(passages, passage_embeddings), start=1):
            ranked.append({
                "filename": filename,
                "passage_index": index,
                "score": cosine_similarity(query_embedding, emb),
                "text": passage,
            })
        ranked.sort(key=lambda item: (-item["score"], item["passage_index"]))
        return self._select_ranked_candidates(
            ranked,
            max_total_chars=max_total_chars,
            max_passages=max_passages,
            selection_mode=selection_mode,
        )

    def _select_ranked_candidates(
        self,
        candidates: list[dict],
        *,
        max_total_chars: int,
        max_passages: int,
        selection_mode: str,
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
                "selection_mode": selection_mode,
            }
        return [], {
            "selected_passage_count": 0,
            "selected_chars": 0,
            "selection_mode": "none",
        }

    def _truncate_to_budget(self, text: str, remaining: int) -> str | None:
        if remaining <= 120:
            return None
        if len(text) <= remaining:
            return text
        if remaining < 180:
            return None
        return text[:remaining].rstrip() + "..."

