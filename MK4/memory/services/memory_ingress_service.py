from __future__ import annotations

from memory.policies.conflict_policy import ConflictPolicy
from memory.policies.extraction_policy import ExtractionPolicy
from memory.policies.retention_policy import RetentionPolicy
from memory.services.evidence_normalization_service import EvidenceNormalizationService
from profile_analysis.services.profile_memory_sync_service import ProfileMemorySyncService
from profile_analysis.stores.uploaded_profile_evidence_store import UploadedProfileEvidenceStore
from project_analysis.stores.project_profile_evidence_store import ProjectProfileEvidenceStore


class MemoryIngressService:
    """Common ingress/apply layer for all memory-producing channels."""

    def __init__(self) -> None:
        self.extraction_policy = ExtractionPolicy()
        self.conflict_policy = ConflictPolicy()
        self.retention_policy = RetentionPolicy()
        self.profile_memory_sync_service = ProfileMemorySyncService()
        self.uploaded_evidence_store = UploadedProfileEvidenceStore()
        self.project_evidence_store = ProjectProfileEvidenceStore()
        self.normalizer = EvidenceNormalizationService()

    def persist_profile_candidate_envelopes(
        self,
        *,
        channel: str,
        owner_id: str,
        envelopes: list[dict],
        default_source_file_path: str | None = None,
    ) -> list[dict]:
        stored: list[dict] = []

        if channel == "uploaded_text":
            self.uploaded_evidence_store.delete_by_source(owner_id)
            for envelope in envelopes or []:
                if str(envelope.get("kind") or "") != "profile_candidate":
                    continue
                source_file_paths = envelope.get("source_file_paths") or []
                source_file_path = ", ".join(source_file_paths) if source_file_paths else (default_source_file_path or "__unknown__")
                stored.append(
                    self.uploaded_evidence_store.add(
                        source_id=owner_id,
                        source_file_path=source_file_path,
                        evidence_type="profile_candidate",
                        topic=envelope.get("topic"),
                        topic_id=envelope.get("topic_id"),
                        candidate_content=envelope.get("candidate_content"),
                        source_strength=envelope.get("source_strength"),
                        evidence_text=envelope.get("evidence_text"),
                        confidence=envelope.get("confidence"),
                    )
                )
            return stored

        if channel == "project_artifact":
            self.project_evidence_store.delete_by_project(owner_id)
            for envelope in envelopes or []:
                if str(envelope.get("kind") or "") != "profile_candidate":
                    continue
                source_file_paths = envelope.get("source_file_paths") or []
                source_file_path = ", ".join(source_file_paths) if source_file_paths else (default_source_file_path or "__unknown__")
                stored.append(
                    self.project_evidence_store.add(
                        project_id=owner_id,
                        source_file_path=source_file_path,
                        evidence_type="profile_candidate",
                        topic=envelope.get("topic"),
                        topic_id=envelope.get("topic_id"),
                        candidate_content=envelope.get("candidate_content"),
                        source_strength=envelope.get("source_strength"),
                        evidence_text=envelope.get("evidence_text"),
                        confidence=envelope.get("confidence"),
                    )
                )
            return stored

        return stored

    def persist_uploaded_profile_candidates(
        self,
        *,
        source_id: str,
        filename: str,
        candidates: list[dict],
    ) -> list[dict]:
        envelopes = self.normalizer.normalize_profile_candidate_envelopes(
            candidates,
            channel="uploaded_text",
            include_source_file_paths=False,
            default_source_file_paths=[filename],
        )
        return self.persist_profile_candidate_envelopes(
            channel="uploaded_text",
            owner_id=source_id,
            envelopes=envelopes,
            default_source_file_path=filename,
        )

    def persist_project_profile_candidates(
        self,
        *,
        project_id: str,
        candidates: list[dict],
    ) -> list[dict]:
        envelopes = self.normalizer.normalize_profile_candidate_envelopes(
            candidates,
            channel="project_artifact",
            include_source_file_paths=True,
        )
        return self.persist_profile_candidate_envelopes(
            channel="project_artifact",
            owner_id=project_id,
            envelopes=envelopes,
        )

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
