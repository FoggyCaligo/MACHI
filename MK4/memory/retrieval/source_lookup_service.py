from __future__ import annotations

from memory.services.profile_evidence_graph import ProfileEvidenceGraph
from memory.services.passage_selection_service import PassageSelectionService
from memory.stores.chat_profile_evidence_store import ChatProfileEvidenceStore
from memory.stores.state_store import StateStore
from profile_analysis.stores.uploaded_profile_evidence_store import UploadedProfileEvidenceStore
from profile_analysis.stores.uploaded_profile_source_store import UploadedProfileSourceStore
from project_analysis.stores.project_profile_evidence_store import ProjectProfileEvidenceStore
from tools.text_embedding import cosine_similarity, embed_text, embed_texts


SOURCE_LOOKUP_LIMIT = 3
SOURCE_LOOKUP_MIN_SIMILARITY = 0.34
SOURCE_LOOKUP_SCAN_LIMIT = 120


class SourceLookupService:
    def __init__(self) -> None:
        self.uploaded_evidence_store = UploadedProfileEvidenceStore()
        self.uploaded_source_store = UploadedProfileSourceStore()
        self.chat_evidence_store = ChatProfileEvidenceStore()
        self.project_evidence_store = ProjectProfileEvidenceStore()
        self.state_store = StateStore()
        self.passage_selector = PassageSelectionService()
        self.profile_graph = ProfileEvidenceGraph()

    def _recent_rows(self, rows: list[dict], limit: int = SOURCE_LOOKUP_SCAN_LIMIT) -> list[dict]:
        ordered = sorted(
            rows or [],
            key=lambda row: row.get("created_at") or row.get("updated_at") or "",
            reverse=True,
        )
        return ordered[:limit]

    def _search_text(self, row: dict) -> str:
        parts = [
            self.profile_graph.normalize_text(row.get("topic")),
            self.profile_graph.normalize_text(row.get("candidate_content")),
            self.profile_graph.normalize_text(row.get("evidence_text")),
            self.profile_graph.normalize_text(row.get("source_file_path")),
            self.profile_graph.normalize_text(row.get("filename")),
            self.profile_graph.normalize_text(row.get("user_request")),
        ]
        return "\n".join(part for part in parts if part)

    def _uploaded_candidates(self) -> list[dict]:
        candidates: list[dict] = []
        for row in self._recent_rows(self.uploaded_evidence_store.list_profile_evidence()):
            source_id = str(row.get("source_id") or "").strip()
            if not source_id:
                continue
            candidates.append(
                {
                    **row,
                    "lookup_key": f"uploaded:{source_id}",
                    "source_kind": "uploaded_profile_source",
                }
            )
        return candidates

    def _chat_candidates(self) -> list[dict]:
        candidates: list[dict] = []
        for row in self._recent_rows(self.chat_evidence_store.list_profile_evidence()):
            evidence_id = str(row.get("id") or "").strip()
            if not evidence_id:
                continue
            candidates.append(
                {
                    **row,
                    "lookup_key": f"chat:{evidence_id}",
                    "source_kind": "chat_profile_evidence",
                }
            )
        return candidates

    def _project_candidates(self) -> list[dict]:
        candidates: list[dict] = []
        for row in self._recent_rows(self.project_evidence_store.list_profile_evidence()):
            evidence_id = str(row.get("id") or "").strip()
            if not evidence_id:
                continue
            candidates.append(
                {
                    **row,
                    "lookup_key": f"project:{evidence_id}",
                    "source_kind": "project_profile_evidence",
                }
            )
        return candidates

    def _score_bonus(self, candidate: dict, active_topic_id: str | None) -> float:
        bonus = 0.0
        if active_topic_id and str(candidate.get("topic_id") or "").strip() == active_topic_id:
            bonus += 0.05
        if candidate.get("source_kind") == "uploaded_profile_source":
            bonus += 0.02
        return bonus

    def _rank_candidates(
        self,
        query: str,
        candidates: list[dict],
        *,
        active_topic_id: str | None = None,
        min_similarity: float = SOURCE_LOOKUP_MIN_SIMILARITY,
    ) -> list[dict]:
        normalized_query = self.profile_graph.normalize_text(query)
        if not normalized_query or not candidates:
            return []

        query_embedding = embed_text(normalized_query, kind="query")
        if not query_embedding:
            return []

        prepared: list[dict] = []
        texts: list[str] = []
        for candidate in candidates:
            text = self._search_text(candidate)
            if not text:
                continue
            prepared.append(candidate)
            texts.append(text)

        if not texts:
            return []

        embeddings = embed_texts(texts, kind="passage")
        scored: list[dict] = []
        for candidate, embedding in zip(prepared, embeddings):
            similarity = cosine_similarity(query_embedding, embedding)
            if similarity < min_similarity:
                continue
            score = similarity + self._score_bonus(candidate, active_topic_id)
            scored.append(
                {
                    **candidate,
                    "_source_lookup_score": score,
                    "_source_lookup_similarity": similarity,
                }
            )

        scored.sort(
            key=lambda item: (
                item.get("_source_lookup_score", 0.0),
                item.get("created_at") or item.get("updated_at") or "",
            ),
            reverse=True,
        )
        return scored

    def _joined_excerpt(self, selected_passages: list[dict]) -> str:
        return "\n\n".join(
            self.profile_graph.normalize_text(item.get("text"))
            for item in selected_passages
            if self.profile_graph.normalize_text(item.get("text"))
        ).strip()

    def _build_uploaded_reference(self, row: dict, query: str) -> dict | None:
        source_id = str(row.get("source_id") or "").strip()
        if not source_id:
            return None

        source = self.uploaded_source_store.get(source_id)
        if not source:
            return None

        filename = self.profile_graph.normalize_text(source.get("filename")) or self.profile_graph.normalize_text(row.get("source_file_path"))
        content = str(source.get("content") or "")
        selected_passages, selection_meta = self.passage_selector.select_followup_passages(
            filename=filename or "__unknown__",
            content=content,
            user_request=query,
            max_total_chars=1600,
            max_passages=4,
        )
        excerpt = self._joined_excerpt(selected_passages)
        if not excerpt:
            selected_passages, selection_meta = self.passage_selector.build_head_excerpt_passages(
                filename=filename or "__unknown__",
                content=content,
                max_total_chars=1200,
                max_passages=3,
            )
            excerpt = self._joined_excerpt(selected_passages)

        if not excerpt:
            return None

        return {
            "_lookup_key": str(row.get("lookup_key") or "").strip(),
            "source_kind": "uploaded_profile_source",
            "source_id": source_id,
            "label": filename or "uploaded_profile_source",
            "topic": self.profile_graph.normalize_text(row.get("topic")) or None,
            "topic_id": str(row.get("topic_id") or "").strip() or None,
            "candidate_content": self.profile_graph.clip_text(row.get("candidate_content"), max_len=180) or None,
            "evidence_hint": self.profile_graph.clip_text(row.get("evidence_text"), max_len=220) or None,
            "excerpt": excerpt,
            "selection_mode": selection_meta.get("selection_mode"),
            "match_score": round(float(row.get("_source_lookup_score") or 0.0), 4),
            "created_at": source.get("created_at") or row.get("created_at"),
        }

    def _build_evidence_reference(self, row: dict) -> dict | None:
        excerpt = self.profile_graph.clip_text(row.get("evidence_text") or row.get("candidate_content"), max_len=520)
        if not excerpt:
            return None

        source_kind = str(row.get("source_kind") or "").strip() or "profile_evidence"
        label = self.profile_graph.normalize_text(row.get("source_file_path"))
        if not label and source_kind == "chat_profile_evidence":
            label = "chat_profile_evidence"
        if not label and source_kind == "project_profile_evidence":
            project_id = self.profile_graph.normalize_text(row.get("project_id"))
            label = f"project:{project_id}" if project_id else "project_profile_evidence"

        return {
            "_lookup_key": str(row.get("lookup_key") or "").strip(),
            "source_kind": source_kind,
            "source_id": str(row.get("id") or "").strip() or str(row.get("lookup_key") or "").strip(),
            "label": label or source_kind,
            "topic": self.profile_graph.normalize_text(row.get("topic")) or None,
            "topic_id": str(row.get("topic_id") or "").strip() or None,
            "candidate_content": self.profile_graph.clip_text(row.get("candidate_content"), max_len=180) or None,
            "evidence_hint": self.profile_graph.clip_text(row.get("evidence_text"), max_len=220) or None,
            "excerpt": excerpt,
            "match_score": round(float(row.get("_source_lookup_score") or 0.0), 4),
            "created_at": row.get("created_at") or row.get("updated_at"),
            "project_id": self.profile_graph.normalize_text(row.get("project_id")) or None,
            "source_file_path": self.profile_graph.normalize_text(row.get("source_file_path")) or None,
        }

    def _build_recent_source_fallback(self, query: str) -> dict | None:
        recent_source_id = str((self.state_store.get_state("recent_profile_source_id") or {}).get("value") or "").strip()
        source: dict | None = None
        if recent_source_id:
            source = self.uploaded_source_store.get(recent_source_id)
        if not source:
            recent_sources = self.uploaded_source_store.list_recent(limit=1)
            source = recent_sources[0] if recent_sources else None
        if not source:
            return None

        source_id = str(source.get("id") or "").strip()
        filename = self.profile_graph.normalize_text(source.get("filename")) or "uploaded_profile_source"
        selected_passages, selection_meta = self.passage_selector.select_followup_passages(
            filename=filename,
            content=str(source.get("content") or ""),
            user_request=query,
            max_total_chars=1400,
            max_passages=3,
        )
        excerpt = self._joined_excerpt(selected_passages)
        if not excerpt:
            return None

        return {
            "_lookup_key": f"uploaded:{source_id}",
            "source_kind": "uploaded_profile_source",
            "source_id": source_id,
            "label": filename,
            "topic": None,
            "topic_id": None,
            "candidate_content": None,
            "evidence_hint": None,
            "excerpt": excerpt,
            "selection_mode": selection_meta.get("selection_mode"),
            "match_score": None,
            "created_at": source.get("created_at"),
        }

    def lookup(
        self,
        query: str,
        *,
        limit: int = SOURCE_LOOKUP_LIMIT,
        active_topic_id: str | None = None,
    ) -> list[dict]:
        candidates = [
            *self._uploaded_candidates(),
            *self._chat_candidates(),
            *self._project_candidates(),
        ]
        ranked = self._rank_candidates(query, candidates, active_topic_id=active_topic_id)

        references: list[dict] = []
        seen_keys: set[str] = set()

        for row in ranked:
            lookup_key = str(row.get("lookup_key") or "").strip()
            if not lookup_key or lookup_key in seen_keys:
                continue

            if row.get("source_kind") == "uploaded_profile_source":
                reference = self._build_uploaded_reference(row, query)
            else:
                reference = self._build_evidence_reference(row)

            if not reference:
                continue

            seen_keys.add(lookup_key)
            references.append(reference)
            if len(references) >= limit:
                break

        if references:
            return self.profile_graph.attach_reference_traces(
                references,
                ranked,
                active_topic_id=active_topic_id,
            )

        fallback = self._build_recent_source_fallback(query)
        if not fallback:
            return []
        return self.profile_graph.attach_reference_traces(
            [fallback],
            [],
            active_topic_id=active_topic_id,
        )
