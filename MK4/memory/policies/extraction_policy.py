from __future__ import annotations

from memory.policies.memory_classification_policy import MemoryClassificationPolicy
from memory.services.topic_router import TopicRouter


class ExtractionPolicy:
    def __init__(self) -> None:
        self.topic_router = TopicRouter()
        self.memory_policy = MemoryClassificationPolicy()

    def extract(self, user_message: str, reply: str, update_bundle: dict, model: str | None = None) -> dict:
        del reply

        bundle = update_bundle or {}
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
            "candidate_evidences": [],
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
                direct_confirm = bool(metadata.get("direct_confirm"))
                classification = self.memory_policy.classify_chat_memory(
                    action_types=action_types,
                    similarity=topic_resolution.similarity,
                    source_strength=envelope.get("source_strength"),
                    direct_confirm=direct_confirm,
                    confidence=envelope.get("confidence"),
                )
                if classification["route"] == "confirmed":
                    result["profiles"].append(
                        {
                            "topic_id": topic_id,
                            "topic": topic,
                            "content": content,
                            "source": "chat_direct_confirm",
                            "confidence": classification["confidence"],
                            "signals": classification["signals"],
                        }
                    )
                elif classification["route"] == "candidate":
                    result["candidate_evidences"].append(
                        {
                            "channel": "chat",
                            "topic_id": topic_id,
                            "topic": topic,
                            "candidate_content": content,
                            "source_strength": envelope.get("source_strength") or "",
                            "confidence": classification["confidence"],
                            "evidence_text": user_message,
                            "direct_confirm": direct_confirm,
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
