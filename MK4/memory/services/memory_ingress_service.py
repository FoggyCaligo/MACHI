from __future__ import annotations

from memory.policies.conflict_policy import ConflictPolicy
from memory.policies.extraction_policy import ExtractionPolicy
from memory.policies.retention_policy import RetentionPolicy
from memory.services.evidence_normalization_service import EvidenceNormalizationService
from profile_analysis.services.profile_memory_sync_service import ProfileMemorySyncService
from profile_analysis.stores.uploaded_profile_evidence_store import UploadedProfileEvidenceStore
from project_analysis.stores.project_profile_evidence_store import ProjectProfileEvidenceStore


class MemoryIngressService:
    """
    Common ingress/apply layer for all memory-producing channels.

    Current scope:
    - chat: update_plan -> extracted -> apply/write/retain
    - uploaded text: stored evidence -> sync/promotion
    - project artifact: stored evidence -> sync/promotion

    Channel-specific extraction still lives in each channel service, but the
    write/apply/sync path converges here so later policy changes land in one
    place.
    """

    def __init__(self) -> None:
        self.extraction_policy = ExtractionPolicy()
        self.conflict_policy = ConflictPolicy()
        self.retention_policy = RetentionPolicy()
        self.profile_memory_sync_service = ProfileMemorySyncService()
        self.uploaded_evidence_store = UploadedProfileEvidenceStore()
        self.project_evidence_store = ProjectProfileEvidenceStore()
        self.normalizer = EvidenceNormalizationService()


    def persist_uploaded_profile_candidates(
        self,
        *,
        source_id: str,
        filename: str,
        candidates: list[dict],
    ) -> list[dict]:
        self.uploaded_evidence_store.delete_by_source(source_id)
        stored: list[dict] = []
        for item in candidates or []:
            candidate = self.normalizer.normalize_profile_candidate(item, include_source_file_paths=False)
            if not candidate:
                continue
            stored.append(
                self.uploaded_evidence_store.add(
                    source_id=source_id,
                    source_file_path=filename,
                    evidence_type="profile_candidate",
                    topic=candidate["topic"],
                    topic_id=candidate.get("topic_id"),
                    candidate_content=candidate["candidate_content"],
                    source_strength=candidate["source_strength"],
                    evidence_text=candidate["evidence_text"],
                    confidence=candidate["confidence"],
                )
            )
        return stored

    def persist_project_profile_candidates(
        self,
        *,
        project_id: str,
        candidates: list[dict],
    ) -> list[dict]:
        self.project_evidence_store.delete_by_project(project_id)
        stored: list[dict] = []
        for item in candidates or []:
            candidate = self.normalizer.normalize_profile_candidate(item, include_source_file_paths=True)
            if not candidate:
                continue
            source_paths = candidate.get("source_file_paths") or []
            source_file_path = ", ".join(source_paths) if source_paths else "__unknown__"
            stored.append(
                self.project_evidence_store.add(
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
            )
        return stored

    def apply_chat_update(
        self,
        *,
        user_message: str,
        reply: str,
        update_plan: dict,
        model: str | None = None,
    ) -> dict:
        extracted = self.extraction_policy.extract(
            user_message=user_message,
            reply=reply,
            update_plan=update_plan,
            model=model,
        )
        self.conflict_policy.apply(extracted)
        self.retention_policy.run()
        return extracted

    def sync_uploaded_source(self, source_id: str) -> dict:
        result = self.profile_memory_sync_service.sync_uploaded_source(source_id)
        self.retention_policy.run()
        return result

    def sync_project(self, project_id: str) -> dict:
        result = self.profile_memory_sync_service.sync_project(project_id)
        self.retention_policy.run()
        return result
