from __future__ import annotations

from memory.policies.extraction_policy import ExtractionPolicy
from memory.policies.retention_policy import RetentionPolicy
from memory.services.evidence_normalization_service import EvidenceNormalizationService
from memory.services.memory_apply_service import MemoryApplyService
from profile_analysis.stores.uploaded_profile_evidence_store import UploadedProfileEvidenceStore
from project_analysis.stores.project_profile_evidence_store import ProjectProfileEvidenceStore


class MemoryIngressService:
    """Common ingress/apply layer for all memory-producing channels."""

    def __init__(self) -> None:
        self.extraction_policy = ExtractionPolicy()
        self.retention_policy = RetentionPolicy()
        self.memory_apply_service = MemoryApplyService()
        self.uploaded_evidence_store = UploadedProfileEvidenceStore()
        self.project_evidence_store = ProjectProfileEvidenceStore()
        self.normalizer = EvidenceNormalizationService()

    def persist_profile_candidate_envelopes(
        self,
        *,
        channel: str,
        owner_id: str,
        source_file_path: str = "__unknown__",
        evidence_envelopes: list[dict] | None = None,
    ) -> list[dict]:
        evidence_envelopes = evidence_envelopes or []
        if channel == "uploaded_text":
            self.uploaded_evidence_store.delete_by_source(owner_id)
            stored: list[dict] = []
            for env in evidence_envelopes:
                if env.get("kind") != "profile_candidate":
                    continue
                meta = env.get("metadata") or {}
                stored.append(
                    self.uploaded_evidence_store.add(
                        source_id=owner_id,
                        source_file_path=source_file_path,
                        evidence_type="profile_candidate",
                        topic=env.get("topic") or "general",
                        topic_id=env.get("topic_id"),
                        candidate_content=env.get("content") or "",
                        source_strength=env.get("source_strength") or "",
                        evidence_text=meta.get("evidence_text") or "",
                        confidence=float(env.get("confidence") or 0.0),
                    )
                )
            return stored

        if channel == "project_artifact":
            self.project_evidence_store.delete_by_project(owner_id)
            stored: list[dict] = []
            for env in evidence_envelopes:
                if env.get("kind") != "profile_candidate":
                    continue
                meta = env.get("metadata") or {}
                source_paths = meta.get("source_file_paths") or []
                joined_path = ", ".join(source_paths) if source_paths else source_file_path
                stored.append(
                    self.project_evidence_store.add(
                        project_id=owner_id,
                        source_file_path=joined_path,
                        evidence_type="profile_candidate",
                        topic=env.get("topic") or "general",
                        topic_id=env.get("topic_id"),
                        candidate_content=env.get("content") or "",
                        source_strength=env.get("source_strength") or "",
                        evidence_text=meta.get("evidence_text") or "",
                        confidence=float(env.get("confidence") or 0.0),
                    )
                )
            return stored
        return []

    def persist_uploaded_profile_candidates(
        self,
        *,
        source_id: str,
        filename: str,
        candidates: list[dict],
    ) -> list[dict]:
        envelopes = self.normalizer.normalize_profile_candidate_envelopes(
            candidates or [],
            channel="uploaded_text",
            include_source_file_paths=False,
        )
        return self.persist_profile_candidate_envelopes(
            channel="uploaded_text",
            owner_id=source_id,
            source_file_path=filename,
            evidence_envelopes=envelopes,
        )

    def persist_project_profile_candidates(
        self,
        *,
        project_id: str,
        candidates: list[dict],
    ) -> list[dict]:
        envelopes = self.normalizer.normalize_profile_candidate_envelopes(
            candidates or [],
            channel="project_artifact",
            include_source_file_paths=True,
        )
        return self.persist_profile_candidate_envelopes(
            channel="project_artifact",
            owner_id=project_id,
            evidence_envelopes=envelopes,
        )

    def apply_chat_update(
        self,
        *,
        user_message: str,
        reply: str,
        update_bundle: dict,
        model: str | None = None,
    ) -> dict:
        extracted = self.extraction_policy.extract(
            user_message=user_message,
            reply=reply,
            update_bundle=update_bundle,
            model=model,
        )
        apply_result = self.memory_apply_service.apply_extracted(extracted)
        self.retention_policy.run()
        return {
            "extracted": extracted,
            "apply_result": apply_result,
        }

    def sync_uploaded_source(self, source_id: str) -> dict:
        result = self.memory_apply_service.sync_uploaded_source(source_id)
        self.retention_policy.run()
        return result

    def sync_project(self, project_id: str) -> dict:
        result = self.memory_apply_service.sync_project(project_id)
        self.retention_policy.run()
        return result
