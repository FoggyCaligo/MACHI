from __future__ import annotations

from memory.policies.memory_classification_policy import MemoryClassificationPolicy
from memory.services.evidence_normalization_service import EvidenceNormalizationService
from memory.services.topic_router import TopicRouter


class ExtractionPolicy:
    def __init__(self) -> None:
        self.topic_router = TopicRouter()
        self.memory_policy = MemoryClassificationPolicy()
        self.normalizer = EvidenceNormalizationService()

    def _legacy_bundle_from_update_plan(self, user_message: str, update_plan: dict) -> dict:
        parsed = {
            "action_types": [a.get("type") for a in update_plan.get("actions", []) if isinstance(a, dict)],
            "state_payloads": update_plan.get("state_payloads"),
            "memory_candidate": {
                "content": update_plan.get("memory_text") or user_message,
                "source_strength": update_plan.get("source_strength"),
                "direct_candidate": bool(update_plan.get("direct_candidate")),
                "confidence": 0.8 if bool(update_plan.get("direct_candidate")) else 0.0,
            }
            if (update_plan.get("memory_text") or user_message) and update_plan.get("source_strength")
            else None,
            "correction_candidate": {
                "content": update_plan.get("memory_text") or user_message,
                "reason": "explicit_correction_or_conflict_candidate",
                "confidence": 0.8,
            }
            if any((a.get("type") == "new_correction") for a in update_plan.get("actions", []) if isinstance(a, dict))
            else None,
            "episode_candidate": {
                "summary": str(update_plan.get("memory_text") or user_message)[:300],
                "raw_ref": update_plan.get("memory_text") or user_message,
                "importance": 0.4,
            }
            if bool(update_plan.get("should_create_episode")) and (update_plan.get("memory_text") or user_message)
            else None,
        }
        bundle = self.normalizer.normalize_chat_update_bundle(parsed)
        bundle.update({
            "actions": update_plan.get("actions", []),
            "memory_text": str(update_plan.get("memory_text") or user_message or "").strip(),
            "source_strength": update_plan.get("source_strength"),
            "direct_candidate": bool(update_plan.get("direct_candidate")),
            "should_create_episode": bool(update_plan.get("should_create_episode")),
        })
        return bundle

    def extract(self, user_message: str, reply: str, update_plan: dict, model: str | None = None) -> dict:
        del reply

        bundle = update_plan if update_plan.get("evidence_envelopes") is not None else self._legacy_bundle_from_update_plan(user_message, update_plan)
        evidence_envelopes = bundle.get("evidence_envelopes") or []
        topic_seed = str(bundle.get("topic_seed") or user_message or "").strip()

        topic_resolution = self.topic_router.resolve(
            user_message=topic_seed,
            model=model,
            use_active_topic=True,
            persist_active=True,
        )
        topic = topic_resolution.topic_summary or "general"
        topic_id = topic_resolution.topic_id

        result = {
            "profiles": [],
            "corrections": [],
            "episodes": [],
            "states": [],
            "discarded": [],
            "topic_resolution": {
                "decision": topic_resolution.decision,
                "topic_id": topic_id,
                "topic": topic,
                "similarity": topic_resolution.similarity,
                "used_active_topic": topic_resolution.used_active_topic,
            },
        }

        action_types = set(bundle.get("action_types") or ["discard"])

        for envelope in evidence_envelopes:
            kind = str(envelope.get("kind") or "").strip()
            content = str(envelope.get("content") or "").strip()
            metadata = envelope.get("metadata") or {}

            if kind == "profile_candidate" and content:
                direct_candidate = bool(metadata.get("direct_candidate"))
                classification = self.memory_policy.classify_chat_memory(
                    user_message=content,
                    action_types=action_types,
                    similarity=topic_resolution.similarity,
                    source_strength=envelope.get("source_strength"),
                    direct_candidate=direct_candidate,
                )
                if self.memory_policy.should_store_chat_profile(classification):
                    result["profiles"].append(
                        {
                            "topic_id": topic_id,
                            "topic": topic,
                            "content": content,
                            "source": "user_explicit_high_value",
                            "confidence": classification["confidence"],
                            "signals": classification["signals"],
                        }
                    )
                else:
                    result["discarded"].append(content)
            elif kind == "correction_candidate" and content:
                result["corrections"].append(
                    {
                        "topic_id": topic_id,
                        "topic": topic,
                        "content": content,
                        "reason": metadata.get("reason") or "explicit_correction_or_conflict_candidate",
                        "source": "user_explicit",
                    }
                )
            elif kind == "episode_candidate" and content:
                result["episodes"].append(
                    {
                        "topic_id": topic_id,
                        "topic": topic,
                        "summary": content[:300],
                        "raw_ref": metadata.get("raw_ref") or content,
                        "importance": float(envelope.get("confidence") or 0.4),
                        "memory_classification": "candidate",
                    }
                )
            elif kind == "state_update":
                key = str(metadata.get("key") or "").strip()
                if key and content:
                    result["states"].append(
                        {
                            "key": key,
                            "value": content,
                            "source": metadata.get("source") or "user_explicit",
                        }
                    )

        result["states"].append({"key": "active_topic_id", "value": topic_id or "", "source": "topic_router"})
        result["states"].append({"key": "active_topic_summary", "value": topic, "source": "topic_router"})
        return result
