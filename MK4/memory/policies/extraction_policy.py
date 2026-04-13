from __future__ import annotations

import time

from memory.policies.memory_classification_policy import MemoryClassificationPolicy
from memory.services.topic_router import TopicRouter


def _log(message: str) -> None:
    print(f"[MEMORY] {message}", flush=True)


class ExtractionPolicy:
    def __init__(self) -> None:
        self.topic_router = TopicRouter()
        self.memory_policy = MemoryClassificationPolicy()

    def _empty_result(self) -> dict:
        return {
            "profiles": [],
            "profile_evidences": [],
            "corrections": [],
            "episodes": [],
            "states": [],
            "discarded": [],
            "topic_resolution": {
                "decision": "skip_noop",
                "topic_id": None,
                "topic": "general",
                "similarity": 0.0,
                "used_active_topic": False,
            },
        }

    def _has_meaningful_envelope(self, evidence_envelopes: list[dict]) -> bool:
        for envelope in evidence_envelopes:
            kind = str(envelope.get("kind") or "").strip()
            content = str(envelope.get("content") or "").strip()
            if kind in {"profile_candidate", "correction_candidate", "episode_candidate"} and content:
                return True
            if kind == "state_update":
                metadata = envelope.get("metadata") or {}
                state_key = str(metadata.get("key") or "").strip()
                if state_key and content:
                    return True
        return False

    def extract(self, user_message: str, reply: str, update_bundle: dict, model: str | None = None) -> dict:
        del reply
        started_at = time.perf_counter()

        bundle = update_bundle or {}
        evidence_envelopes = bundle.get("evidence_envelopes") or []
        if not self._has_meaningful_envelope(evidence_envelopes):
            result = self._empty_result()
            total_elapsed = time.perf_counter() - started_at
            _log(
                "extraction_policy skip | "
                f"reason=no_meaningful_envelope | envelopes={len(evidence_envelopes)} | total={total_elapsed:.2f}s"
            )
            return result

        topic_seed = str(bundle.get("topic_seed") or user_message or "").strip()
        source_message_id = bundle.get("source_message_id")
        response_message_id = bundle.get("response_message_id")

        topic_started_at = time.perf_counter()
        topic_resolution = self.topic_router.resolve(
            user_message=topic_seed,
            model=model,
            use_active_topic=True,
            persist_active=True,
        )
        topic_elapsed = time.perf_counter() - topic_started_at
        topic = topic_resolution.topic_summary or "general"
        topic_id = topic_resolution.topic_id

        result = {
            "profiles": [],
            "profile_evidences": [],
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

        loop_started_at = time.perf_counter()
        for envelope in evidence_envelopes:
            kind = str(envelope.get("kind") or "").strip()
            content = str(envelope.get("content") or "").strip()
            metadata = envelope.get("metadata") or {}

            if kind == "profile_candidate" and content:
                classification = self.memory_policy.classify_chat_memory(
                    action_types=action_types,
                    similarity=topic_resolution.similarity,
                    source_strength=envelope.get("source_strength"),
                    direct_candidate=bool(metadata.get("direct_candidate")),
                    direct_confirm=bool(metadata.get("direct_confirm")),
                    confidence=envelope.get("confidence"),
                    memory_tier=metadata.get("memory_tier"),
                )
                route = classification["route"]
                if route == "discard":
                    result["discarded"].append(content)
                    continue

                evidence = {
                    "channel": "chat",
                    "topic_id": topic_id,
                    "topic": topic,
                    "candidate_content": content,
                    "source_strength": envelope.get("source_strength") or "",
                    "confidence": classification["confidence"],
                    "signals": classification["signals"],
                    "memory_tier": route,
                    "direct_confirm": bool(metadata.get("direct_confirm")),
                    "evidence_text": user_message,
                    "source_message_id": source_message_id,
                    "response_message_id": response_message_id,
                }
                result["profile_evidences"].append(evidence)
                if route == "confirmed":
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
                state_key = str(metadata.get("key") or "").strip()
                state_value = content
                if state_key and state_value:
                    result["states"].append(
                        {
                            "key": state_key,
                            "value": state_value,
                            "source": metadata.get("source") or "user_explicit",
                        }
                    )
        loop_elapsed = time.perf_counter() - loop_started_at

        if topic_id:
            result["states"].append(
                {
                    "key": "active_topic_id",
                    "value": topic_id,
                    "source": "topic_router",
                }
            )

        total_elapsed = time.perf_counter() - started_at
        _log(
            "extraction_policy extract | "
            f"topic_router={topic_elapsed:.2f}s | envelope_loop={loop_elapsed:.2f}s | "
            f"profiles={len(result['profiles'])} | evidences={len(result['profile_evidences'])} | "
            f"corrections={len(result['corrections'])} | episodes={len(result['episodes'])} | total={total_elapsed:.2f}s"
        )
        return result
