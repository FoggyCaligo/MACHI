from __future__ import annotations

from pathlib import Path
import builtins

import pytest

from MK5.tools.terminal_tools import TerminalToolSuite
from MK5.tools.llm_client import _parse_model_turn
from MK5.tools.tool_runtime import ToolCall
from MK5.tools.workspace_tools import WorkspaceFileToolSuite
from MK5.tools import web_search
from MK5.tools.web_search import HttpWebSearchTool, SearchHit


@pytest.mark.asyncio
async def test_workspace_file_tool_can_write_and_read(tmp_path: Path) -> None:
    suite = WorkspaceFileToolSuite(tmp_path)
    registry = suite.build_registry()

    await registry.run(ToolCall(tool="workspace_file", arguments={
        "action": "write",
        "path": "notes/test.txt",
        "content": "hello",
    }))
    result = await registry.run(ToolCall(tool="workspace_file", arguments={
        "action": "read",
        "path": "notes/test.txt",
    }))

    assert result["content"] == "hello"


@pytest.mark.asyncio
async def test_terminal_tool_blocks_destructive_command(tmp_path: Path) -> None:
    suite = TerminalToolSuite(tmp_path)
    registry = suite.build_registry()

    with pytest.raises(ValueError):
        await registry.run(ToolCall(tool="terminal_command", arguments={"command": "rm -rf ."}))


def test_model_turn_parser_accepts_plain_text_fallback() -> None:
    turn = _parse_model_turn("검색 결과를 바탕으로 답변합니다.")

    assert turn.final_answer == "검색 결과를 바탕으로 답변합니다."
    assert turn.tool_calls == []


@pytest.mark.asyncio
async def test_internet_search_runs_per_concept_node(monkeypatch: pytest.MonkeyPatch) -> None:
    searched: list[tuple[str, str]] = []

    async def fake_ddg(query: str) -> list[SearchHit]:
        searched.append(("ddg", query))
        return [SearchHit(title=f"{query}-ddg", url=f"https://example.com/{query}/ddg", snippet="result", source="duckduckgo")]

    async def fake_wiki(query: str, lang: str) -> list[SearchHit]:
        searched.append((f"wiki_{lang}", query))
        return [SearchHit(title=f"{query}-{lang}", url=f"https://example.com/{query}/{lang}", snippet="result", source=f"wikipedia_{lang}")]

    monkeypatch.setattr("MK5.tools.web_search._ddg_search", fake_ddg)
    monkeypatch.setattr("MK5.tools.web_search._wiki_search", fake_wiki)

    result = await HttpWebSearchTool()._run({
        "query": "파이썬 러스트 비교",
        "search_nodes": ["파이썬", "러스트"],
    })

    assert result["search_nodes"] == ["파이썬", "러스트"]
    assert {item["query_node"] for item in result["results"]} == {"파이썬", "러스트"}
    assert ("ddg", "파이썬") in searched
    assert ("wiki_ko", "러스트") in searched


@pytest.mark.asyncio
async def test_internet_search_falls_back_to_whole_query_without_node_heuristics(monkeypatch: pytest.MonkeyPatch) -> None:
    searched: list[str] = []

    async def fake_ddg(query: str) -> list[SearchHit]:
        searched.append(query)
        return [SearchHit(title="whole-query", url="https://example.com", snippet="result", source="duckduckgo")]

    async def fake_wiki(query: str, lang: str) -> list[SearchHit]:
        searched.append(query)
        return []

    monkeypatch.setattr("MK5.tools.web_search._ddg_search", fake_ddg)
    monkeypatch.setattr("MK5.tools.web_search._wiki_search", fake_wiki)

    query = "글록의 특징과 총기시장에서의 의의"
    result = await HttpWebSearchTool()._run({"query": query})

    assert result["search_nodes"] == [query]
    assert query in searched


def test_duckduckgo_missing_dependency_degrades_to_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def fake_import(name: str, *args, **kwargs):
        if name == "ddgs":
            raise ModuleNotFoundError("No module named 'ddgs'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    assert web_search._ddg_search_sync("글록") == []


@pytest.mark.asyncio
async def test_wikipedia_search_strips_html_snippets(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "query": {
                    "search": [{
                        "title": "글록",
                        "snippet": "<span>글록</span> 권총",
                    }]
                }
            }

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            return None

        async def get(self, *args, **kwargs) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr(web_search.httpx, "AsyncClient", FakeClient)

    hits = await web_search._wiki_search("글록", "ko")

    assert hits[0].snippet == "글록 권총"

