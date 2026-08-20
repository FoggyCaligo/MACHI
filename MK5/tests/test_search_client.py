from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from MK5.tools.search_client import SearchBundle, SearchResult, search_structured


class SearchClientTest(unittest.IsolatedAsyncioTestCase):
    async def test_search_structured_returns_empty_bundle_when_all_sources_fail(self) -> None:
        async def fail_ddg(_query: str):
            raise RuntimeError("ddg failed")

        async def fail_wiki(_query: str, _lang: str):
            raise RuntimeError("wiki blocked")

        with (
            patch("MK5.tools.search_client._ddg_search", side_effect=fail_ddg),
            patch("MK5.tools.search_client._wiki_search", side_effect=fail_wiki),
        ):
            bundle = await search_structured("그래프")

        self.assertEqual(bundle, SearchBundle(query="그래프", results=[]))

    async def test_search_structured_keeps_successful_sources_when_wiki_fails(self) -> None:
        async def ok_ddg(query: str):
            return [
                SearchResult(
                    query=query,
                    source="ddg",
                    title="Graph",
                    url="https://example.org/graph",
                    snippet="A graph is a relational structure.",
                    rank=1,
                )
            ]

        async def fail_wiki(_query: str, _lang: str):
            raise RuntimeError("403 forbidden")

        with (
            patch("MK5.tools.search_client._ddg_search", side_effect=ok_ddg),
            patch("MK5.tools.search_client._wiki_search", side_effect=fail_wiki),
        ):
            bundle = await search_structured("그래프")

        self.assertEqual(len(bundle.results), 1)
        self.assertEqual(bundle.results[0].source, "ddg")


if __name__ == "__main__":
    unittest.main()

