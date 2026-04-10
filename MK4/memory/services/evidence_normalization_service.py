from __future__ import annotations

import json
import re
from typing import Any

from memory.policies.memory_classification_policy import SOURCE_STRENGTH_ORDER


class EvidenceNormalizationService:
    """Normalize structured evidence/update payloads across channels.

    This layer does not interpret raw language. It validates and shapes
    already-structured outputs produced upstream by extractors/resolvers.
    """

    ALLOWED_ACTION_TYPES = {
        "discard",
        "profile_candidate",
        "state_update",
        "new_correction",
        "new_episode",
    }
    ALLOWED_ENVELOPE_KINDS = {
        "profile_candidate",
        "state_update",
        "correction_candidate",
        "episode_candidate",
    }

    @staticmethod
    def clean_text(value: Any) -> str:
        return str(value or "").strip()

    @staticmethod
    def extract_json_object(text: str) -> dict[str, Any]:
        raw = str(text or "").strip()
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return {}
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def bounded_confidence(value: Any, default: float = 0.0) -> float:
        try:
            score = float(value)
        except (TypeError, ValueError):
            return default
        return min(max(score, 0.0), 1.0)

    @staticmethod
    def normalize_source_strength(value: Any) -> str:
        text = str(value or "").strip()
        return text if text in SOURCE_STRENGTH_ORDER else ""

    def normalize_actions(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return ["discard"]

        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            action = self.clean_text(item)
            if action not in self.ALLOWED_ACTION_TYPES or action in seen:
                continue
            seen.add(action)
            normalized.append(action)
        return normalized or ["discard"]

    def normalize_state_payloads(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []

        normalized: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            key = self.clean_text(item.get("key"))
            payload_value = self.clean_text(item.get("value"))
            if not key or not payload_value:
                continue
            normalized.append(
                {
                    "key": key,
                    "value": payload_value,
                    "source": self.clean_text(item.get("source")) or "user_explicit",
                    "confidence": self.bounded_confidence(item.get("confidence"), default=0.6),
                }
            )
        return normalized

    def normalize_memory_candidate(self, value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        content = self.clean_text(value.get("content"))
        if not content:
            return None
        return {
            "content": content,
            "source_strength": self.normalize_source_strength(value.get("source_strength")),
            "direct_candidate": bool(value.get("direct_candidate")),
            "confidence": self.bounded_confidence(value.get("confidence"), default=0.0),
        }

    def normalize_correction_candidate(self, value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        content = self.clean_text(value.get("content"))
        if not content:
            return None
        reason = self.clean_text(value.get("reason")) or "user_explicit_correction"
        return {
            "content": content,
            "reason": reason,
            "confidence": self.bounded_confidence(value.get("confidence"), default=0.7),
        }

    def normalize_episode_candidate(self, value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        summary = self.clean_text(value.get("summary"))
        if not summary:
            return None
        raw_ref = self.clean_text(value.get("raw_ref")) or summary
        return {
            "summary": summary,
            "raw_ref": raw_ref,
            "importance": self.bounded_confidence(value.get("importance"), default=0.5),
        }

    def normalize_profile_candidate(
        self,
        value: Any,
        *,
        include_source_file_paths: bool = False,
    ) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None

        topic = self.clean_text(value.get("topic"))
        candidate_content = self.clean_text(value.get("candidate_content"))
        evidence_text = self.clean_text(value.get("evidence_text"))
        if not topic or not candidate_content:
            return None

        normalized = {
            "topic": topic,
            "candidate_content": candidate_content,
            "source_strength": self.normalize_source_strength(value.get("source_strength")),
            "confidence": self.bounded_confidence(value.get("confidence"), default=0.0),
            "evidence_text": evidence_text,
        }

        if include_source_file_paths:
            source_file_paths = value.get("source_file_paths") or []
            if not isinstance(source_file_paths, list):
                source_file_paths = []
            normalized["source_file_paths"] = [self.clean_text(x) for x in source_file_paths if self.clean_text(x)]

        if value.get("topic_id"):
            normalized["topic_id"] = self.clean_text(value.get("topic_id"))
        if value.get("topic_resolution"):
            normalized["topic_resolution"] = value.get("topic_resolution")

        return normalized

    def normalize_chat_update(self, parsed: dict[str, Any]) -> dict[str, Any]:
        action_types = self.normalize_actions(parsed.get("action_types"))
        state_payloads = self.normalize_state_payloads(parsed.get("state_payloads"))
        memory_candidate = self.normalize_memory_candidate(parsed.get("memory_candidate"))
        correction_candidate = self.normalize_correction_candidate(parsed.get("correction_candidate"))
        episode_candidate = self.normalize_episode_candidate(parsed.get("episode_candidate"))

        if memory_candidate and "profile_candidate" not in action_types:
            action_types.append("profile_candidate")
        if correction_candidate and "new_correction" not in action_types:
            action_types.append("new_correction")
        if episode_candidate and "new_episode" not in action_types:
            action_types.append("new_episode")
        if state_payloads and "state_update" not in action_types:
            action_types.append("state_update")

        meaningful = [a for a in action_types if a != "discard"]
        if meaningful:
            action_types = meaningful
        else:
            action_types = ["discard"]

        return {
            "action_types": action_types,
            "state_payloads": state_payloads,
            "memory_candidate": memory_candidate,
            "correction_candidate": correction_candidate,
            "episode_candidate": episode_candidate,
        }

    def build_evidence_envelope(
        self,
        *,
        channel: str,
        kind: str,
        topic: str = "",
        topic_id: str = "",
        content: str = "",
        source_strength: str = "",
        confidence: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        kind = self.clean_text(kind)
        if kind not in self.ALLOWED_ENVELOPE_KINDS:
            return None
        envelope = {
            "channel": self.clean_text(channel),
            "kind": kind,
            "topic": self.clean_text(topic),
            "topic_id": self.clean_text(topic_id),
            "content": self.clean_text(content),
            "source_strength": self.normalize_source_strength(source_strength),
            "confidence": self.bounded_confidence(confidence, default=0.0),
            "metadata": metadata or {},
        }
        if kind in {"profile_candidate", "correction_candidate", "episode_candidate"} and not envelope["content"]:
            return None
        return envelope

    def normalize_chat_update_bundle(self, parsed: dict[str, Any]) -> dict[str, Any]:
        normalized = self.normalize_chat_update(parsed)
        envelopes: list[dict[str, Any]] = []

        memory_candidate = normalized.get("memory_candidate")
        if memory_candidate:
            env = self.build_evidence_envelope(
                channel="chat",
                kind="profile_candidate",
                content=memory_candidate.get("content") or "",
                source_strength=memory_candidate.get("source_strength") or "",
                confidence=memory_candidate.get("confidence") or 0.0,
                metadata={"direct_candidate": bool(memory_candidate.get("direct_candidate"))},
            )
            if env:
                envelopes.append(env)

        correction_candidate = normalized.get("correction_candidate")
        if correction_candidate:
            env = self.build_evidence_envelope(
                channel="chat",
                kind="correction_candidate",
                content=correction_candidate.get("content") or "",
                confidence=correction_candidate.get("confidence") or 0.0,
                metadata={"reason": correction_candidate.get("reason") or ""},
            )
            if env:
                envelopes.append(env)

        episode_candidate = normalized.get("episode_candidate")
        if episode_candidate:
            env = self.build_evidence_envelope(
                channel="chat",
                kind="episode_candidate",
                content=episode_candidate.get("summary") or "",
                confidence=episode_candidate.get("importance") or 0.0,
                metadata={"raw_ref": episode_candidate.get("raw_ref") or ""},
            )
            if env:
                envelopes.append(env)

        for state in normalized.get("state_payloads") or []:
            env = self.build_evidence_envelope(
                channel="chat",
                kind="state_update",
                content=state.get("value") or "",
                confidence=state.get("confidence") or 0.0,
                metadata={
                    "key": state.get("key") or "",
                    "source": state.get("source") or "",
                },
            )
            if env:
                envelopes.append(env)

        topic_seed = ""
        for env in envelopes:
            if env.get("content"):
                topic_seed = self.clean_text(env.get("content"))
                break

        return {
            "channel": "chat",
            "topic_seed": topic_seed,
            "action_types": normalized.get("action_types") or ["discard"],
            "evidence_envelopes": envelopes,
        }

    def normalize_profile_candidate_envelopes(
        self,
        values: Any,
        *,
        channel: str,
        include_source_file_paths: bool = False,
    ) -> list[dict[str, Any]]:
        if not isinstance(values, list):
            return []
        envelopes: list[dict[str, Any]] = []
        for item in values:
            candidate = self.normalize_profile_candidate(item, include_source_file_paths=include_source_file_paths)
            if not candidate:
                continue
            metadata: dict[str, Any] = {
                "evidence_text": candidate.get("evidence_text") or "",
            }
            if candidate.get("topic_resolution"):
                metadata["topic_resolution"] = candidate.get("topic_resolution")
            if candidate.get("source_file_paths"):
                metadata["source_file_paths"] = candidate.get("source_file_paths")
            env = self.build_evidence_envelope(
                channel=channel,
                kind="profile_candidate",
                topic=candidate.get("topic") or "",
                topic_id=candidate.get("topic_id") or "",
                content=candidate.get("candidate_content") or "",
                source_strength=candidate.get("source_strength") or "",
                confidence=candidate.get("confidence") or 0.0,
                metadata=metadata,
            )
            if env:
                envelopes.append(env)
        return envelopes
