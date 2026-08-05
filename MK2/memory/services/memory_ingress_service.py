from __future__ import annotations

import time

from memory.policies.extraction_policy import ExtractionPolicy
from memory.policies.memory_classification_policy import MemoryClassificationPolicy
from memory.policies.retention_policy import RetentionPolicy
from memory.services.evidence_normalization_service import EvidenceNormalizationService
from memory.services.memory_apply_service import MemoryApplyService
from profile_analysis.stores.uploaded_profile_evidence_store import UploadedProfileEvidenceStore
from project_analysis.stores.project_profile_evidence_store import ProjectProfileEvidenceStore


def _log(message: str) -> None:
    print(f"[MEMORY] {message}", flush=True)


class MemoryIngressService:
    """Common ingress/apply layer for all memory-producing channels."""

    def __init__(self) -> None:
        self.extraction_policy = ExtractionPolicy()
        self.memory_policy = MemoryClassificationPolicy()
        self.retention_policy = RetentionPolicy()
        self.memory_apply_service = MemoryApplyService()
        self.uploaded_evidence_store = UploadedProfileEvidenceStore()
        self.project_evidence_store = ProjectProfileEvidenceStore()
        self.normalizer = EvidenceNormalizationService()

    def _resolve_profile_memory_tier(self, env: dict) -> tuple[str, bool]:
        meta = env.get("metadata") or {}
        evidence = {
            "candidate_content": env.get("content") or "",
            "source_strength": env.get("source_strength") or "",
            "confidence": env.get("confidence") or 0.0,
            "direct_confirm": bool(meta.get("direct_confirm")),
            "memory_tier": meta.get("memory_tier") or "",
        }
        classification = self.memory_policy.classify_evidence(evidence)
        return classification["route"], bool(meta.get("direct_confirm"))

    def persist_profile_candidate_envelopes(
        self,
        *,
        channel: str,
        owner_id: str,
        source_file_path: str = "__unknown__",
        evidence_envelopes: list[dict] | None = None,
        source_file_hash_by_path: dict[str, str] | None = None,
    ) -> list[dict]:
        evidence_envelopes = evidence_envelopes or []
        if channel == "uploaded_text":
            self.uploaded_evidence_store.delete_by_source(owner_id)
            stored: list[dict] = []
            for env in evidence_envelopes:
                if env.get("kind") != "profile_candidate":
                    continue
                meta = env.get("metadata") or {}
                memory_tier, direct_confirm = self._resolve_profile_memory_tier(env)
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
                        direct_confirm=direct_confirm,
                        memory_tier=memory_tier,
                    )
                )
            return stored

        if channel == "project_artifact":
            stored: list[dict] = []
            hash_by_path = {
                str(path).replace("\\", "/").strip(): str(value or "").strip()
                for path, value in (source_file_hash_by_path or {}).items()
                if str(path or "").strip()
            }
            for env in evidence_envelopes:
                if env.get("kind") != "profile_candidate":
                    continue
                meta = env.get("metadata") or {}
                source_paths = [
                    str(path or "").replace("\\", "/").strip()
                    for path in (meta.get("source_file_paths") or [])
                    if str(path or "").strip()
                ]
                display_path = source_paths[0] if len(source_paths) == 1 else ", ".join(source_paths) if source_paths else source_file_path
                source_hashes = {path: hash_by_path[path] for path in source_paths if hash_by_path.get(path)}
                memory_tier, direct_confirm = self._resolve_profile_memory_tier(env)
                stored.append(
                    self.project_evidence_store.add(
                        project_id=owner_id,
                        source_file_path=display_path,
                        source_file_paths=source_paths,
                        source_file_hashes=source_hashes,
                        evidence_type="profile_candidate",
                        topic=env.get("topic") or "general",
                        topic_id=env.get("topic_id"),
                        candidate_content=env.get("content") or "",
                        source_strength=env.get("source_strength") or "",
                        evidence_text=meta.get("evidence_text") or "",
                        confidence=float(env.get("confidence") or 0.0),
                        direct_confirm=direct_confirm,
                        memory_tier=memory_tier,
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
        source_file_hash_by_path: dict[str, str] | None = None,
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
            source_file_hash_by_path=source_file_hash_by_path,
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
        started_at = time.perf_counter()
        bundle = dict(update_bundle or {})
        bundle["source_message_id"] = source_message_id
        bundle["response_message_id"] = response_message_id

        t0 = time.perf_counter()
        extracted = self.extraction_policy.extract(
            user_message=user_message,
            reply=reply,
            update_bundle=bundle,
            model=model,
        )
        extraction_policy_elapsed = time.perf_counter() - t0

        t0 = time.perf_counter()
        apply_result = self.memory_apply_service.apply_extracted(extracted)
        apply_elapsed = time.perf_counter() - t0

        t0 = time.perf_counter()
        self.retention_policy.run()
        retention_elapsed = time.perf_counter() - t0

        total_elapsed = time.perf_counter() - started_at
        _log(
            "memory_ingress apply_chat_update | "
            f"extraction_policy={extraction_policy_elapsed:.2f}s | "
            f"apply={apply_elapsed:.2f}s | retention={retention_elapsed:.2f}s | "
            f"total={total_elapsed:.2f}s"
        )
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

    def reconcile_topics(self, topic_refs: list[dict]) -> dict:
        result = self.memory_apply_service.reconcile_topics(topic_refs)
        self.retention_policy.run()
        return result
