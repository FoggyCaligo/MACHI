import unittest
from unittest.mock import patch

from memory.services.chat_evidence_service import ChatEvidenceService
from memory.services.evidence_normalization_service import EvidenceNormalizationService


class EvidenceNormalizationServiceTests(unittest.TestCase):
    def test_extract_json_object_accepts_fenced_json(self) -> None:
        normalizer = EvidenceNormalizationService()

        parsed = normalizer.extract_json_object(
            """```json
            {"action_types": ["discard"], "state_payloads": []}
            ```"""
        )

        self.assertEqual(parsed["action_types"], ["discard"])

    def test_normalize_chat_update_accepts_plural_candidates(self) -> None:
        normalizer = EvidenceNormalizationService()

        normalized = normalizer.normalize_chat_update(
            {
                "action_types": ["profile_candidate", "new_correction", "new_episode"],
                "memory_candidates": [
                    {
                        "content": "likes structural thinking",
                        "source_strength": "explicit_self_statement",
                        "direct_confirm": False,
                        "confidence": 0.82,
                        "memory_tier": "candidate",
                    },
                    {
                        "content": "likes writing",
                        "source_strength": "repeated_behavior",
                        "direct_confirm": False,
                        "confidence": 0.61,
                        "memory_tier": "general",
                    },
                ],
                "correction_candidates": [
                    {
                        "content": "that is not what I meant",
                        "reason": "user correction",
                        "target_kind": "response_behavior",
                        "confidence": 0.74,
                    }
                ],
                "episode_candidates": [
                    {
                        "summary": "working on MK4",
                        "raw_ref": "working on MK4 today",
                        "importance": 0.65,
                    }
                ],
            }
        )

        self.assertEqual(len(normalized["memory_candidates"]), 2)
        self.assertEqual(len(normalized["correction_candidates"]), 1)
        self.assertEqual(len(normalized["episode_candidates"]), 1)
        self.assertEqual(normalized["memory_candidate"]["content"], "likes structural thinking")

    def test_normalize_chat_update_bundle_creates_multiple_envelopes(self) -> None:
        normalizer = EvidenceNormalizationService()

        bundle = normalizer.normalize_chat_update_bundle(
            {
                "current_conversation_summary": "user describes values and interests",
                "action_types": ["profile_candidate", "new_correction"],
                "memory_candidates": [
                    {
                        "content": "values happiness over accumulation",
                        "source_strength": "explicit_self_statement",
                        "direct_confirm": False,
                        "confidence": 0.91,
                        "memory_tier": "confirmed",
                    },
                    {
                        "content": "interested in philosophy",
                        "source_strength": "repeated_behavior",
                        "direct_confirm": False,
                        "confidence": 0.58,
                        "memory_tier": "candidate",
                    },
                ],
                "correction_candidates": [
                    {
                        "content": "double-check historical claims",
                        "reason": "user correction",
                        "target_kind": "topic_fact",
                        "confidence": 0.77,
                    }
                ],
            }
        )

        profile_envelopes = [item for item in bundle["evidence_envelopes"] if item["kind"] == "profile_candidate"]
        correction_envelopes = [item for item in bundle["evidence_envelopes"] if item["kind"] == "correction_candidate"]

        self.assertEqual(len(profile_envelopes), 2)
        self.assertEqual(len(correction_envelopes), 1)
        self.assertEqual(bundle["topic_seed"], "user describes values and interests")


class ChatEvidenceServicePromptTests(unittest.TestCase):
    def test_build_user_prompt_includes_recent_user_only_context(self) -> None:
        service = ChatEvidenceService()
        recent_rows = [
            {"role": "user", "content": "I like writing and fiction."},
            {"role": "assistant", "content": "Tell me more."},
            {"role": "user", "content": "I also care about structural thinking."},
            {"role": "assistant", "content": "Understood."},
            {"role": "user", "content": "I want you to double-check things."},
        ]

        with patch.object(service.raw_message_store, "recent", return_value=recent_rows):
            prompt = service._build_user_prompt("I want you to double-check things.")

        self.assertIn("[recent_user_messages]", prompt)
        self.assertIn("I like writing and fiction.", prompt)
        self.assertIn("I also care about structural thinking.", prompt)
        self.assertNotIn("Tell me more.", prompt)
        self.assertEqual(prompt.count("[latest_user_message]"), 1)


if __name__ == "__main__":
    unittest.main()
