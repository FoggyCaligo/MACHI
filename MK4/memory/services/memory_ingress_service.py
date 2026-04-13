from __future__ import annotations

from memory.policies.extraction_policy import ExtractionPolicy
from memory.services.evidence_normalization_service import EvidenceNormalizationService
from memory.services.memory_apply_service import MemoryApplyService
from memory.services.retention_policy import RetentionPolicy
from profile_analysis.stores.uploaded_profile_evidence_store import UploadedProfileEvidenceStore
from project_analysis.stores.project_profile_evidence_store import ProjectProfileEvidenceStore


class MemoryIngressService:
    def __init__(self) -> None:
        self.extraction_policy = ExtractionPolicy()
        self.memory_apply_service = MemoryApplyService()
        self.retention_policy = RetentionPolicy()
        self.normalizer = EvidenceNormalizationService()
        self.uploaded_evidence_store = UploadedProfileEvidenceStore()
        self.project_evidence_store = ProjectProfileEvidenceStore()

    def persist_profile_candidate_envelopes(
        self,
        *,
        channel: str,
        owner_id: str,
        evidence_envelopes: list[dict],
        source_file_path: str | None = None,
    ) -> list[dict]:
        persisted: list[dict] = []
        for envelope in evidence_envelopes or []:
            if envelope.get("kind") != "profile_candidate":
                continue
            metadata = envelope.get("metadata") or {}
            evidence_text = str(metadata.get("evidence_text") or "").strip()
            source_paths = metadata.get("source_file_paths") or []
            resolved_source_paths: list[str] = []
            if isinstance(source_paths, list):
                resolved_source_paths = [str(path).strip() for path in source_paths if str(path).strip()]
            if source_file_path and source_file_path not in resolved_source_paths:
                resolved_source_paths = [source_file_path, *resolved_source_paths]
            if not resolved_source_paths:
                resolved_source_paths = [source_file_path or "unknown_source"]

            for path in resolved_source_paths:
                if channel == "uploaded_text":
                    row = self.uploaded_evidence_store.add(
                        source_id=owner_id,
                        source_file_path=path,
                        evidence_type="profile_candidate",
                        evidence_text=evidence_text,
                        confidence=envelope.get("confidence"),
                        topic=envelope.get("topic"),
                        topic_id=envelope.get("topic_id") or None,
                        candidate_content=envelope.get("content"),
                        source_strength=envelope.get("source_strength"),
                    )
                elif channel == "project_artifact":
                    row = self.project_evidence_store.add(
                        project_id=owner_id,
                        source_file_path=path,
                        evidence_type="profile_candidate",
                        evidence_text=evidence_text,
                        confidence=envelope.get("confidence"),
                        topic=envelope.get("topic"),
                        topic_id=envelope.get("topic_id") or None,
                        candidate_content=envelope.get("content"),
                        source_strength=envelope.get("source_strength"),
                    )
                else:
                    continue
                persisted.append(row)
        return persisted

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
            include_source_file_paths=True,
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
        source_message_id: str | None = None,
        response_message_id: str | None = None,
    ) -> dict:
        extracted = self.extraction_policy.extract(
            user_message=user_message,
            reply=reply,
            update_bundle=update_bundle,
            model=model,
        )
        apply_result = self.memory_apply_service.apply_extracted(
            extracted,
            source_message_id=source_message_id,
            response_message_id=response_message_id,
        )
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
