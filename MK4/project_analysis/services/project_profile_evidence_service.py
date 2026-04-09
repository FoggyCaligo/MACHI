from pathlib import Path

from config import (
    PROJECT_REPLY_MAX_CONTINUATIONS,
    PROJECT_REPLY_NUM_PREDICT,
    PROJECT_REPLY_TIMEOUT,
    PROJECT_PROFILE_EVIDENCE_ANSWER_SYSTEM_PROMPT_PATH,
    PROJECT_PROFILE_EVIDENCE_EXTRACT_SYSTEM_PROMPT_PATH,
)
from memory.policies.memory_classification_policy import (
    MemoryClassificationPolicy,
    SOURCE_STRENGTH_ORDER,
)
from memory.stores.correction_store import CorrectionStore
from memory.stores.profile_store import ProfileStore
from memory.services.evidence_extraction_service import EvidenceExtractionService
from memory.services.topic_router import TopicRouter
from memory.stores.topic_store import TopicStore
from prompts.prompt_loader import load_prompt_text
from project_analysis.stores.project_file_store import ProjectFileStore
from project_analysis.stores.project_profile_evidence_store import (
    ProjectProfileEvidenceStore,
)
from tools.response_runner import ResponseRunner


PROFILE_DOC_EXTENSIONS = {".txt", ".md", ".markdown", ".rst"}
PROFILE_NAME_HINTS = {
    "readme.md",
    "readme.txt",
    "about.md",
    "profile.md",
    "notes.md",
    "blog.md",
    "blog.txt",
    "plan.md",
    "planning.md",
    "retrospective.md",
}
PROFILE_QUESTION_KEYWORDS = {
    "성향",
    "프로필",
    "스타일",
    "선호",
    "need",
    "니즈",
    "작동 방식",
    "나에 대해",
    "어떤 사람",
    "나답",
    "습관",
    "판단 기준",
    "불편해하는",
}

class ProjectProfileEvidenceService:
    def __init__(self) -> None:
        self.file_store = ProjectFileStore()
        self.evidence_store = ProjectProfileEvidenceStore()
        self.profile_store = ProfileStore()
        self.correction_store = CorrectionStore()
        self.topic_store = TopicStore()
        self.topic_router = TopicRouter()
        self.extraction_service = EvidenceExtractionService(timeout=120, num_predict=384, retry_num_predict=256)
        self.answer_runner = ResponseRunner(
            timeout=PROJECT_REPLY_TIMEOUT,
            num_predict=PROJECT_REPLY_NUM_PREDICT,
            max_continuations=PROJECT_REPLY_MAX_CONTINUATIONS,
        )
        self.memory_policy = MemoryClassificationPolicy()

    def is_profile_question(self, question: str) -> bool:
        q = (question or "").lower()
        return any(keyword in q for keyword in PROFILE_QUESTION_KEYWORDS)

    def _select_documents(self, project_id: str) -> list[dict]:
        files = self.file_store.list_full_by_project(project_id)
        selected: list[dict] = []

        for file in files:
            path = file.get("path") or ""
            ext = (file.get("ext") or "").lower()
            name = Path(path).name.lower()
            content = (file.get("content") or "").strip()

            if not content:
                continue

            if ext in PROFILE_DOC_EXTENSIONS or name in PROFILE_NAME_HINTS:
                selected.append(
                    {
                        "path": path,
                        "content": content,
                    }
                )

        return selected[:8]

    def _build_extract_user_prompt(
        self,
        project_id: str,
        documents: list[dict],
        *,
        max_docs: int = 8,
        max_chars_per_doc: int = 3500,
    ) -> str:
        blocks = []
        for idx, doc in enumerate(documents[:max_docs], start=1):
            content = doc["content"]
            if len(content) > max_chars_per_doc:
                content = content[:max_chars_per_doc].rstrip() + "\n..."

            blocks.append(
                f"[자료 {idx}]\n"
                f"프로젝트: {project_id}\n"
                f"경로: {doc['path']}\n"
                f"본문:\n{content}"
            )

        return "[분석 자료]\n" + "\n\n".join(blocks)

    def _build_answer_messages(self, question: str, evidences: list[dict]) -> list[dict]:
        system_prompt = load_prompt_text(PROJECT_PROFILE_EVIDENCE_ANSWER_SYSTEM_PROMPT_PATH)

        blocks = []
        for idx, evidence in enumerate(evidences, start=1):
            text = (evidence.get("evidence_text") or "").strip()
            if len(text) > 1500:
                text = text[:1500].rstrip() + "\n..."

            blocks.append(
                f"[evidence {idx}]\n"
                f"topic: {evidence.get('topic')}\n"
                f"candidate_content: {evidence.get('candidate_content')}\n"
                f"source_strength: {evidence.get('source_strength')}\n"
                f"source_file_path: {evidence.get('source_file_path')}\n"
                f"confidence: {evidence.get('confidence')}\n"
                f"근거: {text}"
            )

        user_prompt = (
            f"[질문]\n{question}\n\n"
            f"[프로필 evidence]\n" + "\n\n".join(blocks)
        )

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    def _extract_json_array(self, text: str) -> list[dict]:
        result = self.extraction_service.parse_profile_candidates(
            text,
            normalize_source_strength=self.memory_policy.normalize_source_strength,
            include_source_file_paths=True,
        )

        for item in result:
            if item.get("source_strength") not in SOURCE_STRENGTH_ORDER:
                item["source_strength"] = "repeated_behavior"

        return result


    def _resolve_candidate_topic(self, candidate: dict, model: str | None = None) -> dict:
        candidate_content = self._normalize_text(str(candidate.get("candidate_content") or ""))
        raw_topic = self._normalize_text(str(candidate.get("topic") or ""))
        evidence_text = self._normalize_text(str(candidate.get("evidence_text") or ""))

        routing_text = candidate_content
        if raw_topic:
            routing_text = f"{routing_text}\n{raw_topic}".strip()
        if evidence_text:
            routing_text = f"{routing_text}\n{evidence_text[:280]}".strip()
        # 저장용 후보 분류이므로 현재 대화의 active topic/state는 건드리지 않는다.
        resolution = self.topic_router.resolve(
            user_message=routing_text,
            model=model,
            use_active_topic=False,
            persist_active=False,
        )

        routed = dict(candidate)
        routed["topic_id"] = resolution.topic_id
        routed["topic"] = resolution.topic_summary or raw_topic or "general"
        routed["topic_resolution"] = {
            "decision": resolution.decision,
            "similarity": resolution.similarity,
        }
        return routed

    def _normalize_text(self, text: str) -> str:
        return " ".join((text or "").strip().lower().split())

    def _same_meaning(self, a: str, b: str) -> bool:
        na = self._normalize_text(a)
        nb = self._normalize_text(b)
        if not na or not nb:
            return False
        return na == nb or na in nb or nb in na

    def _build_candidate_clusters(self, evidences: list[dict]) -> list[dict]:
        clusters: dict[tuple[str, str], dict] = {}

        for evidence in evidences:
            topic_id = str(evidence.get("topic_id") or "").strip() or None
            topic = self._topic_label(evidence.get("topic"), topic_id)
            candidate_content = (evidence.get("candidate_content") or "").strip()
            source_strength = self.memory_policy.normalize_source_strength(evidence.get("source_strength"))

            if not candidate_content:
                continue

            classification = self.memory_policy.classify_evidence(evidence)
            if classification["route"] == "general":
                continue

            topic_key = topic_id or self._normalize_text(topic)
            key = (topic_key, self._normalize_text(candidate_content))

            if key not in clusters:
                clusters[key] = {
                    "topic": topic,
                    "topic_id": topic_id,
                    "candidate_content": candidate_content,
                    "evidence_ids": [],
                    "project_ids": set(),
                    "source_paths": set(),
                    "confidence_values": [],
                    "source_strength_counts": {
                        "explicit_self_statement": 0,
                        "repeated_behavior": 0,
                        "temporary_interest": 0,
                    },
                    "linked_profile_ids": set(),
                    "direct_confirm_count": 0,
                    "memory_value_hits": 0,
                }

            cluster = clusters[key]
            if not cluster.get("topic_id") and topic_id:
                cluster["topic_id"] = topic_id
            cluster["topic"] = self._topic_label(cluster.get("topic"), cluster.get("topic_id"))
            cluster["evidence_ids"].append(str(evidence.get("id") or ""))
            cluster["project_ids"].add(str(evidence.get("project_id") or ""))
            cluster["source_paths"].add(str(evidence.get("source_file_path") or ""))
            cluster["confidence_values"].append(float(evidence.get("confidence") or 0.0))
            cluster["source_strength_counts"][source_strength] = (
                cluster["source_strength_counts"].get(source_strength, 0) + 1
            )

            classification = self.memory_policy.classify_evidence(evidence)
            if classification["route"] == "confirmed":
                cluster["direct_confirm_count"] += 1
            cluster["memory_value_hits"] += len(classification["signals"])

            linked_profile_id = str(evidence.get("linked_profile_id") or "").strip()
            if linked_profile_id:
                cluster["linked_profile_ids"].add(linked_profile_id)

        result: list[dict] = []
        for cluster in clusters.values():
            confidence_values = cluster["confidence_values"] or [0.0]
            source_strength_counts = cluster["source_strength_counts"]

            primary_strength = "repeated_behavior"
            if source_strength_counts.get("explicit_self_statement", 0) > 0:
                primary_strength = "explicit_self_statement"
            elif source_strength_counts.get("repeated_behavior", 0) > 0:
                primary_strength = "repeated_behavior"

            result.append(
                {
                    "topic": cluster["topic"],
                    "topic_id": cluster.get("topic_id"),
                    "candidate_content": cluster["candidate_content"],
                    "evidence_ids": cluster["evidence_ids"],
                    "evidence_count": len(cluster["evidence_ids"]),
                    "distinct_group_count": len([x for x in cluster["project_ids"] if x]),
                    "distinct_source_count": len([x for x in cluster["source_paths"] if x]),
                    "avg_confidence": sum(confidence_values) / len(confidence_values),
                    "max_confidence": max(confidence_values),
                    "primary_strength": primary_strength,
                    "explicit_count": source_strength_counts.get("explicit_self_statement", 0),
                    "repeated_count": source_strength_counts.get("repeated_behavior", 0),
                    "linked_profile_ids": cluster["linked_profile_ids"],
                    "direct_confirm_count": cluster["direct_confirm_count"],
                    "memory_value_hits": cluster["memory_value_hits"],
                }
            )

        result.sort(
            key=lambda item: (
                -SOURCE_STRENGTH_ORDER.get(item["primary_strength"], 0),
                -item["evidence_count"],
                -item["distinct_source_count"],
                -item["avg_confidence"],
                item["topic"],
            )
        )
        return result

    def _is_promotable_cluster(self, cluster: dict) -> tuple[bool, str]:
        return self.memory_policy.is_promotable_cluster(cluster)

    def _promotion_confidence(self, cluster: dict) -> float:
        return self.memory_policy.promotion_confidence(cluster)

    def _topic_label(self, topic: str | None, topic_id: str | None) -> str:
        if topic:
            return str(topic).strip() or "general"
        return self.topic_store.get_topic_summary(topic_id)

    def _load_topic_corrections(self, topic: str | None = None, topic_id: str | None = None) -> list[dict]:
        if hasattr(self.correction_store, "list_active_by_topic"):
            return self.correction_store.list_active_by_topic(topic=topic, topic_id=topic_id, limit=5)

        if hasattr(self.correction_store, "search"):
            query = topic or self.topic_store.get_topic_summary(topic_id)
            rows = self.correction_store.search(query, limit=5)
            filtered: list[dict] = []
            for row in rows:
                status = str(row.get("status") or "").lower()
                if not status or status == "active":
                    filtered.append(row)
            return filtered

        return []

    def _has_conflicting_active_correction(self, candidate_content: str, topic: str | None = None, topic_id: str | None = None) -> bool:
        active_corrections = self._load_topic_corrections(topic=topic, topic_id=topic_id)
        for correction in active_corrections:
            correction_content = str(correction.get("content") or "").strip()
            if not correction_content:
                continue
            if not self._same_meaning(correction_content, candidate_content):
                return True
        return False

    def _promote_confirmed_profiles(self) -> dict:
        evidences = self.evidence_store.list_candidate_evidence()
        clusters = self._build_candidate_clusters(evidences)

        promoted_profiles = 0
        linked_existing_profiles = 0
        blocked_by_correction = 0
        blocked_by_existing_profile_conflict = 0
        pending_candidates = 0

        for cluster in clusters:
            topic_id = cluster.get("topic_id")
            topic = cluster["topic"]
            candidate_content = cluster["candidate_content"]

            promotable, _reason = self._is_promotable_cluster(cluster)
            if not promotable:
                pending_candidates += 1
                continue

            if self._has_conflicting_active_correction(candidate_content, topic=topic, topic_id=topic_id):
                blocked_by_correction += 1
                continue

            active_profile = self.profile_store.get_active_by_topic(topic=topic, topic_id=topic_id)

            if active_profile:
                active_content = str(active_profile.get("content") or "").strip()
                if self._same_meaning(active_content, candidate_content):
                    linked_count = self.evidence_store.link_profile_for_candidate(
                        topic_id=active_profile.get("topic_id") or topic_id,
                        topic=topic,
                        candidate_content=candidate_content,
                        profile_id=active_profile["id"],
                    )
                    if linked_count > 0:
                        linked_existing_profiles += 1
                    continue

                blocked_by_existing_profile_conflict += 1
                continue

            new_profile_id = self.profile_store.insert_profile(
                topic=topic,
                topic_id=topic_id,
                content=candidate_content,
                source=f"artifact_promotion_v1:{cluster['primary_strength']}",
                confidence=self._promotion_confidence(cluster),
            )
            self.evidence_store.link_profile_for_candidate(
                topic_id=topic_id,
                topic=topic,
                candidate_content=candidate_content,
                profile_id=new_profile_id,
            )
            promoted_profiles += 1

        return {
            "promoted_profiles": promoted_profiles,
            "linked_existing_profiles": linked_existing_profiles,
            "blocked_by_correction": blocked_by_correction,
            "blocked_by_existing_profile_conflict": blocked_by_existing_profile_conflict,
            "pending_candidates": pending_candidates,
        }

    def extract_and_store(self, project_id: str, model: str | None = None) -> dict:
        documents = self._select_documents(project_id)
        self.evidence_store.delete_by_project(project_id)

        if not documents:
            return {
                "stored": False,
                "document_count": 0,
                "source_files": [],
                "candidate_count": 0,
            }

        user_prompt = self._build_extract_user_prompt(
            project_id=project_id,
            documents=documents,
            max_docs=8,
            max_chars_per_doc=3000,
        )
        retry_user_prompt = self._build_extract_user_prompt(
            project_id=project_id,
            documents=documents,
            max_docs=4,
            max_chars_per_doc=1600,
        )
        extract_result = self.extraction_service.run_extract(
            system_prompt_path=PROJECT_PROFILE_EVIDENCE_EXTRACT_SYSTEM_PROMPT_PATH,
            user_prompt=user_prompt,
            retry_user_prompt=retry_user_prompt,
            model=model,
            require_complete=True,
        )
        candidates = [self._resolve_candidate_topic(candidate, model=model) for candidate in self._extract_json_array(extract_result.text)]

        for candidate in candidates:
            source_paths = candidate.get("source_file_paths") or []
            source_file_path = ", ".join(source_paths) if source_paths else "__unknown__"

            self.evidence_store.add(
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

        return {
            "stored": True,
            "document_count": len(documents),
            "source_files": [doc["path"] for doc in documents],
            "candidate_count": len(candidates),
        }

    def sync_to_memory(self, project_id: str) -> dict:
        evidences = self.evidence_store.list_unapplied_by_project(project_id)

        processed = 0
        linked_to_existing_active_profile = 0
        skipped = 0

        for evidence in evidences:
            topic_id = str(evidence.get("topic_id") or "").strip() or None
            topic = self._topic_label(evidence.get("topic"), topic_id)
            candidate_content = (evidence.get("candidate_content") or "").strip()
            source_strength = self.memory_policy.normalize_source_strength(evidence.get("source_strength"))

            if not candidate_content:
                self.evidence_store.mark_applied(evidence["id"])
                skipped += 1
                processed += 1
                continue

            classification = self.memory_policy.classify_evidence(evidence)
            if classification["route"] == "general":
                self.evidence_store.mark_applied(evidence["id"])
                skipped += 1
                processed += 1
                continue

            active_profile = self.profile_store.get_active_by_topic(topic=topic, topic_id=topic_id)
            if active_profile and self._same_meaning(active_profile.get("content", ""), candidate_content):
                self.evidence_store.mark_applied(
                    evidence["id"],
                    linked_profile_id=active_profile["id"],
                )
                linked_to_existing_active_profile += 1
                processed += 1
                continue

            self.evidence_store.mark_applied(evidence["id"])
            processed += 1

        promotion_result = self._promote_confirmed_profiles()

        return {
            "processed": processed,
            "inserted_profiles": promotion_result["promoted_profiles"],
            "added_corrections": 0,
            "linked_to_existing_active_profile": linked_to_existing_active_profile,
            "promoted_profiles": promotion_result["promoted_profiles"],
            "linked_existing_profiles": promotion_result["linked_existing_profiles"],
            "blocked_by_correction": promotion_result["blocked_by_correction"],
            "blocked_by_existing_profile_conflict": promotion_result["blocked_by_existing_profile_conflict"],
            "pending_candidates": promotion_result["pending_candidates"],
            "skipped": skipped,
        }

    def answer_from_project(
        self,
        project_id: str,
        question: str,
        model: str | None = None,
    ) -> dict | None:
        evidences = self.evidence_store.list_by_project(project_id)
        if not evidences:
            self.extract_and_store(project_id, model=model)
            self.sync_to_memory(project_id)
            evidences = self.evidence_store.list_by_project(project_id)

        if not evidences:
            return None

        messages = self._build_answer_messages(question=question, evidences=evidences)
        answer = self.answer_runner.run(messages, model=model).text

        used_evidence = [
            {
                "topic": item.get("topic"),
                "source_file_path": item.get("source_file_path"),
                "confidence": item.get("confidence"),
                "source_strength": item.get("source_strength"),
            }
            for item in evidences
        ]

        return {
            "answer": answer,
            "used_profile_evidence": used_evidence,
        }