from memory.policies.memory_classification_policy import MemoryClassificationPolicy
from memory.services.evidence_normalization_service import EvidenceNormalizationService
from memory.services.topic_router import TopicRouter


class ExtractionPolicy:
    def __init__(self) -> None:
        self.topic_router = TopicRouter()
        self.memory_policy = MemoryClassificationPolicy()
        self.normalizer = EvidenceNormalizationService()

    def extract(self, user_message: str, reply: str, update_plan: dict, model: str | None = None) -> dict:
        bundle = self.normalizer.normalize_chat_update_bundle(update_plan or {}, user_message=user_message)
        envelopes = bundle.get("evidence_envelopes") or []
        topic_seed = str(bundle.get("topic_seed") or "").strip() or str(user_message or "").strip()

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

        for envelope in envelopes:
            kind = str(envelope.get("kind") or "").strip()

            if kind == "correction_candidate":
                result["corrections"].append(
                    {
                        "topic_id": topic_id,
                        "topic": topic,
                        "content": envelope.get("content", ""),
                        "reason": envelope.get("reason", "user_explicit_correction"),
                        "source": "user_explicit",
                        "confidence": envelope.get("confidence", 0.7),
                    }
                )
                continue

            if kind == "profile_candidate":
                classification = self.memory_policy.classify_chat_memory(
                    action_types={"profile_candidate"},
                    similarity=topic_resolution.similarity,
                    source_strength=envelope.get("source_strength"),
                    direct_candidate=bool(envelope.get("direct_candidate")),
                    confidence=envelope.get("confidence"),
                )
                if classification.get("route") == "candidate":
                    result["profiles"].append(
                        {
                            "topic_id": topic_id,
                            "topic": topic,
                            "content": envelope.get("content", ""),
                            "source": "user_explicit_candidate",
                            "confidence": classification.get("confidence", envelope.get("confidence", 0.0)),
                            "signals": classification.get("signals", []),
                            "memory_classification": classification.get("route"),
                        }
                    )
                continue

            if kind == "state_update":
                result["states"].append(
                    {
                        "key": envelope.get("key", ""),
                        "value": envelope.get("value", ""),
                        "source": envelope.get("source", "user_explicit"),
                        "confidence": envelope.get("confidence", 0.6),
                    }
                )
                continue

            if kind == "episode_candidate":
                result["episodes"].append(
                    {
                        "topic_id": topic_id,
                        "topic": topic,
                        "summary": envelope.get("summary", ""),
                        "raw_ref": envelope.get("raw_ref"),
                        "importance": envelope.get("importance", 0.5),
                        "memory_classification": "episode_candidate",
                    }
                )
                continue

        result["states"].append(
            {
                "key": "active_topic_id",
                "value": topic_id or "",
                "source": "topic_router",
            }
        )
        result["states"].append(
            {
                "key": "active_topic_summary",
                "value": topic,
                "source": "topic_router",
            }
        )

        if (
            not result["profiles"]
            and not result["corrections"]
            and not result["episodes"]
            and not any((str(e.get("kind") or "") == "state_update") for e in envelopes)
        ):
            cleaned = str(user_message or "").strip()
            if cleaned:
                result["discarded"].append(cleaned)

        return result
