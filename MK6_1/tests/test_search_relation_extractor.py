from __future__ import annotations

import unittest
from typing import Any

from MK6_1.core.thinking.search_relation_extractor import extract_relation_candidates
from MK6_1.tools.search_client import SearchResult


class SearchRelationExtractorTest(unittest.IsolatedAsyncioTestCase):
    async def test_extract_relation_candidates_success(self) -> None:
        async def fake_llm_chat(_system: str, _user: str, _model: str | None, **_kwargs: Any) -> str:
            return (
                '{"relations": ['
                '{"subject":"글록","predicate":"is_a","object":"권총","connect_type":"flow",'
                '"confidence":0.92,"evidence":"Glock is a series of pistols.",'
                '"source_title":"Glock","source_url":"https://example.org/glock"}'
                "]}")

        results = [
            SearchResult(
                query="글록에 대해 설명해줘",
                source="wiki_en",
                title="Glock",
                url="https://example.org/glock",
                snippet="Glock is a series of pistols.",
                rank=1,
            )
        ]

        candidates = await extract_relation_candidates(
            user_input="글록에 대해 설명해줘",
            query="글록에 대해 설명해줘",
            search_results=results,
            seed_concepts=["글록"],
            llm_chat_fn=fake_llm_chat,
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].subject, "글록")
        self.assertEqual(candidates[0].predicate, "is_a")
        self.assertEqual(candidates[0].object, "권총")
        self.assertEqual(candidates[0].connect_type, "flow")

    async def test_extract_relation_candidates_invalid_schema_raises(self) -> None:
        async def fake_llm_chat(_system: str, _user: str, _model: str | None, **_kwargs: Any) -> str:
            return (
                '{"relations": ['
                '{"subject":"글록","predicate":"is_a","object":"권총","connect_type":"flow",'
                '"confidence":1.7,"evidence":"bad confidence"}'
                "]}"
            )

        with self.assertRaises(RuntimeError):
            await extract_relation_candidates(
                user_input="글록에 대해 설명해줘",
                query="글록",
                search_results=[
                    SearchResult(
                        query="글록",
                        source="ddg",
                        title="Glock",
                        url="https://example.org/glock",
                        snippet="Glock is a series of pistols.",
                        rank=1,
                    )
                ],
                seed_concepts=["글록"],
                llm_chat_fn=fake_llm_chat,
            )

    async def test_extract_relation_candidates_nested_relations(self) -> None:
        async def fake_llm_chat(_system: str, _user: str, _model: str | None, **_kwargs: Any) -> str:
            return (
                '{"data":{"relations":['
                '{"subject":"글록","predicate":"has_part","object":"슬라이드","connect_type":"flow",'
                '"confidence":0.88,"evidence":"It has a slide.","source_title":"Glock","source_url":null}'
                ']}}'
            )

        candidates = await extract_relation_candidates(
            user_input="글록에 대해 설명해줘",
            query="글록",
            search_results=[
                SearchResult(
                    query="글록",
                    source="ddg",
                    title="Glock",
                    url="https://example.org/glock",
                    snippet="It has a slide.",
                    rank=1,
                )
            ],
            seed_concepts=["글록"],
            llm_chat_fn=fake_llm_chat,
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].predicate, "has_part")

    async def test_extract_relation_candidates_requests_json_response_format(self) -> None:
        captured_kwargs: dict[str, Any] = {}

        async def fake_llm_chat(
            _system: str,
            _user: str,
            _model: str | None,
            **kwargs: Any,
        ) -> str:
            captured_kwargs.update(kwargs)
            return '{"relations": []}'

        candidates = await extract_relation_candidates(
            user_input="글록에 대해 설명해줘",
            query="글록",
            search_results=[
                SearchResult(
                    query="글록",
                    source="ddg",
                    title="Glock",
                    url="https://example.org/glock",
                    snippet="Glock is a series of pistols.",
                    rank=1,
                )
            ],
            seed_concepts=["글록"],
            llm_chat_fn=fake_llm_chat,
        )

        self.assertEqual(candidates, [])
        self.assertEqual(captured_kwargs["response_format"], "json")
        self.assertEqual(captured_kwargs["think"], False)


if __name__ == "__main__":
    unittest.main()
