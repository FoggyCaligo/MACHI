from __future__ import annotations

import unittest
from typing import Any

from MK4.core.thinking.search_relation_extractor import extract_relation_candidates
from MK4.tools.search_client import SearchResult


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

    async def test_extract_relation_candidates_keeps_structured_output_opt_in(self) -> None:
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
        self.assertIsNone(captured_kwargs["response_format"])
        self.assertEqual(captured_kwargs["think"], False)

    async def test_extract_relation_candidates_normalizes_mechanism_to_flow(self) -> None:
        async def fake_llm_chat(_system: str, _user: str, _model: str | None, **_kwargs: Any) -> str:
            return (
                '{"relations": ['
                '{"subject":"그래프구조","predicate":"supports","object":"장기기억","connect_type":"mechanism",'
                '"confidence":0.81,"evidence":"Graph structure supports long-term memory.",'
                '"source_title":"Example","source_url":"https://example.org"}'
                "]}"
            )

        candidates = await extract_relation_candidates(
            user_input="그래프구조로 장기기억을 만드는 프로젝트야",
            query="그래프구조",
            search_results=[
                SearchResult(
                    query="그래프구조",
                    source="ddg",
                    title="Example",
                    url="https://example.org",
                    snippet="Graph structure supports long-term memory.",
                    rank=1,
                )
            ],
            seed_concepts=["그래프구조", "장기기억"],
            llm_chat_fn=fake_llm_chat,
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].connect_type, "flow")


if __name__ == "__main__":
    unittest.main()

