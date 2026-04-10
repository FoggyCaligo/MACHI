from __future__ import annotations

import json
import re
from typing import Any

from memory.policies.memory_classification_policy import SOURCE_STRENGTH_ORDER


class EvidenceNormalizationService:
    """Normalize structured evidence/update payloads across channels.

    This layer does not interpret raw language. It only validates and shapes
    already-structured outputs produced upstream by model-based extractors.
    """

    ALLOWED_ACTION_TYPES = {
        "discard",
        "profile_candidate",
        "state_update",
        "new_correction",
        "new_episode",
    }
    ALLOWED_CHANNELS = {"chat", "uploaded_text", "project_artifact"}
    ALLOWED_ENVELOPE_KINDS = {
        "profile_candidate",
        "correction_candidate",
        "state_update",
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
    def bounded_importance(value: Any, default: float = 0.5) -> float:
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
            "importance": self.bounded_importance(value.get("importance"), default=0.5),
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

    def normalize_profile_candidate_envelope(
        self,
        value: Any,
        *,
        channel: str,
        include_source_file_paths: bool = False,
        default_source_file_paths: list[str] | None = None,
    ) -> dict[str, Any] | None:
        normalized = self.normalize_profile_candidate(
            value,
            include_source_file_paths=include_source_file_paths,
        )
        if not normalized:
            return None

        resolved_channel = channel if channel in self.ALLOWED_CHANNELS else ""
        if not resolved_channel:
            return None

        source_file_paths = normalized.get("source_file_paths") or []
        if not source_file_paths and default_source_file_paths:
            source_file_paths = [self.clean_text(x) for x in default_source_file_paths if self.clean_text(x)]

        envelope = {
            "channel": resolved_channel,
            "kind": "profile_candidate",
            "topic": normalized.get("topic"),
            "topic_id": normalized.get("topic_id"),
            "candidate_content": normalized.get("candidate_content"),
            "source_strength": normalized.get("source_strength"),
            "confidence": normalized.get("confidence"),
            "evidence_text": normalized.get("evidence_text"),
            "source_file_paths": source_file_paths,
        }
        if normalized.get("topic_resolution"):
            envelope["topic_resolution"] = normalized.get("topic_resolution")
        return envelope

    def normalize_profile_candidate_envelopes(
        self,
        values: Any,
        *,
        channel: str,
        include_source_file_paths: bool = False,
        default_source_file_paths: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        if not isinstance(values, list):
            return []
        envelopes: list[dict[str, Any]] = []
        for item in values:
            envelope = self.normalize_profile_candidate_envelope(
                item,
                channel=channel,
                include_source_file_paths=include_source_file_paths,
                default_source_file_paths=default_source_file_paths,
            )
            if envelope:
                envelopes.append(envelope)
        return envelopes

    def _normalize_chat_envelope(self, value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None

        channel = self.clean_text(value.get("channel")) or "chat"
        kind = self.clean_text(value.get("kind"))
        if channel not in self.ALLOWED_CHANNELS or channel != "chat":
            return None
        if kind not in self.ALLOWED_ENVELOPE_KINDS:
            return None

        if kind == "profile_candidate":
            candidate = self.normalize_memory_candidate(
                {
                    "content": value.get("content"),
                    "source_strength": value.get("source_strength"),
                    "direct_candidate": value.get("direct_candidate"),
                    "confidence": value.get("confidence"),
                }
            )
            if not candidate:
                return None
            return {
                "channel": "chat",
                "kind": kind,
                **candidate,
            }

        if kind == "correction_candidate":
            correction = self.normalize_correction_candidate(value)
            if not correction:
                return None
            return {
                "channel": "chat",
                "kind": kind,
                **correction,
            }

        if kind == "episode_candidate":
            episode = self.normalize_episode_candidate(value)
            if not episode:
                return None
            return {
                "channel": "chat",
                "kind": kind,
                **episode,
            }

        if kind == "state_update":
            states = self.normalize_state_payloads([value])
            if not states:
                return None
            return {
                "channel": "chat",
                "kind": kind,
                **states[0],
            }

        return None

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

    def normalize_chat_update_bundle(self, parsed: dict[str, Any], *, user_message: str = "") -> dict[str, Any]:
        if isinstance(parsed, dict) and isinstance(parsed.get("evidence_envelopes"), list):
            envelopes = [
                envelope
                for envelope in (self._normalize_chat_envelope(item) for item in parsed.get("evidence_envelopes") or [])
                if envelope
            ]
            topic_seed = self.clean_text(parsed.get("topic_seed")) or self.clean_text(user_message)
            return {
                "channel": "chat",
                "topic_seed": topic_seed,
                "evidence_envelopes": envelopes,
            }

        normalized = self.normalize_chat_update(parsed if isinstance(parsed, dict) else {})
        envelopes: list[dict[str, Any]] = []
        memory_candidate = normalized.get("memory_candidate")
        correction_candidate = normalized.get("correction_candidate")
        episode_candidate = normalized.get("episode_candidate")
        state_payloads = normalized.get("state_payloads") or []

        if memory_candidate:
            envelopes.append(
                {
                    "channel": "chat",
                    "kind": "profile_candidate",
                    **memory_candidate,
                }
            )
        if correction_candidate:
            envelopes.append(
                {
                    "channel": "chat",
                    "kind": "correction_candidate",
                    **correction_candidate,
                }
            )
        if episode_candidate:
            envelopes.append(
                {
                    "channel": "chat",
                    "kind": "episode_candidate",
                    **episode_candidate,
                }
            )
        for state in state_payloads:
            envelopes.append(
                {
                    "channel": "chat",
                    "kind": "state_update",
                    **state,
                }
            )

        topic_seed = (
            (correction_candidate or {}).get("content")
            or (memory_candidate or {}).get("content")
            or (episode_candidate or {}).get("summary")
            or self.clean_text(user_message)
        )

        return {
            "channel": "chat",
            "topic_seed": self.clean_text(topic_seed),
            "evidence_envelopes": envelopes,
        }
