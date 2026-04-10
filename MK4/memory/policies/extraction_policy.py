from memory.policies.memory_classification_policy import MemoryClassificationPolicy
from memory.services.topic_router import TopicRouter


class ExtractionPolicy:
    def __init__(self) -> None:
        self.topic_router = TopicRouter()
        self.memory_policy = MemoryClassificationPolicy()

    def extract(self, user_message: str, reply: str, update_plan: dict, model: str | None = None) -> dict:
        memory_candidate = update_plan.get("memory_candidate") or {}
        correction_candidate = update_plan.get("correction_candidate") or {}
        episode_candidate = update_plan.get("episode_candidate") or {}
        state_payloads = update_plan.get("state_payloads") or []
        action_types = set(update_plan.get("action_types") or [])

        topic_seed = (
            str(correction_candidate.get("content") or "").strip()
            or str(memory_candidate.get("content") or "").strip()
            or str(episode_candidate.get("summary") or "").strip()
            or str(user_message or "").strip()
        )

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

        if correction_candidate:
            result["corrections"].append(
                {
                    "topic_id": topic_id,
                    "topic": topic,
                    "content": correction_candidate.get("content", ""),
                    "reason": correction_candidate.get("reason", "user_explicit_correction"),
                    "source": "user_explicit",
                    "confidence": correction_candidate.get("confidence", 0.7),
                }
            )

        if memory_candidate:
            classification = self.memory_policy.classify_chat_memory(
                action_types=action_types,
                similarity=topic_resolution.similarity,
                source_strength=memory_candidate.get("source_strength"),
                direct_candidate=bool(memory_candidate.get("direct_candidate")),
                confidence=memory_candidate.get("confidence"),
            )
            route = classification.get("route")
            # NOTE:
            # Chat-side separate general/candidate stores do not exist yet.
            # Until that layer is added, only candidate-level chat memory is
            # written into profiles to avoid leaking general memory into the
            # default injected profile surface.
            if route == "candidate":
                result["profiles"].append(
                    {
                        "topic_id": topic_id,
                        "topic": topic,
                        "content": memory_candidate.get("content", ""),
                        "source": "user_explicit_candidate",
                        "confidence": classification.get("confidence", memory_candidate.get("confidence", 0.0)),
                        "signals": classification.get("signals", []),
                        "memory_classification": route,
                    }
                )

        for payload in state_payloads:
            result["states"].append(
                {
                    "key": payload.get("key", ""),
                    "value": payload.get("value", ""),
                    "source": payload.get("source", "user_explicit"),
                    "confidence": payload.get("confidence", 0.6),
                }
            )

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

        if episode_candidate:
            result["episodes"].append(
                {
                    "topic_id": topic_id,
                    "topic": topic,
                    "summary": episode_candidate.get("summary", ""),
                    "raw_ref": episode_candidate.get("raw_ref"),
                    "importance": episode_candidate.get("importance", 0.5),
                    "memory_classification": "episode_candidate",
                }
            )

        if (
            not result["profiles"]
            and not result["corrections"]
            and not result["episodes"]
            and not state_payloads
        ):
            cleaned = str(user_message or "").strip()
            if cleaned:
                result["discarded"].append(cleaned)

        return result
