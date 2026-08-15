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
async def test_workspace_file_tool_can_create_update_and_read(tmp_path: Path) -> None:
    suite = WorkspaceFileToolSuite(tmp_path)
    registry = suite.build_registry()

    await registry.run(ToolCall(tool="workspace_file", arguments={
        "action": "create",
        "path": "notes/test.txt",
        "content": "hello",
    }))
    await registry.run(ToolCall(tool="workspace_file", arguments={
        "action": "update",
        "path": "notes/test.txt",
        "content": "goodbye",
    }))
    result = await registry.run(ToolCall(tool="workspace_file", arguments={
        "action": "read",
        "path": "notes/test.txt",
    }))

    assert result["content"] == "goodbye"


@pytest.mark.asyncio
async def test_workspace_file_tool_appends_utf8_text(tmp_path: Path) -> None:
    suite = WorkspaceFileToolSuite(tmp_path)
    registry = suite.build_registry()

    await registry.run(ToolCall(tool="workspace_file", arguments={
        "action": "create",
        "path": "tags.txt",
        "content": "고음\n",
    }))
    result = await registry.run(ToolCall(tool="workspace_file", arguments={
        "action": "update",
        "path": "tags.txt",
        "content": "\"감성\"\n\"샤워\"\n",
        "mode": "append",
    }))
    read_result = await registry.run(ToolCall(tool="workspace_file", arguments={
        "action": "read",
        "path": "tags.txt",
    }))

    assert result["ok"] is True
    assert read_result["content"] == "고음\n\"감성\"\n\"샤워\"\n"


@pytest.mark.asyncio
async def test_workspace_file_tool_replaces_exact_utf8_text(tmp_path: Path) -> None:
    suite = WorkspaceFileToolSuite(tmp_path)
    registry = suite.build_registry()

    await registry.run(ToolCall(tool="workspace_file", arguments={
        "action": "create",
        "path": "tags.txt",
        "content": "\"감성\"\n\"샤워\"\n",
    }))
    result = await registry.run(ToolCall(tool="workspace_file", arguments={
        "action": "update",
        "path": "tags.txt",
        "old": "\"감성\"\n\"샤워\"",
        "new": "감성\n샤워",
    }))
    read_result = await registry.run(ToolCall(tool="workspace_file", arguments={
        "action": "read",
        "path": "tags.txt",
    }))

    assert result["ok"] is True
    assert result["replacements"] == 1
    assert read_result["content"] == "감성\n샤워\n"


@pytest.mark.asyncio
async def test_workspace_file_tool_returns_not_found_result_instead_of_raising(tmp_path: Path) -> None:
    suite = WorkspaceFileToolSuite(tmp_path)
    registry = suite.build_registry()

    result = await registry.run(ToolCall(tool="workspace_file", arguments={
        "action": "read",
        "path": "architecture.md",
    }))

    assert result["ok"] is False
    assert result["error"] == "not_found"
    assert result["path"] == "architecture.md"


@pytest.mark.asyncio
async def test_workspace_file_tool_can_access_parent_and_absolute_paths(tmp_path: Path) -> None:
    main_root = tmp_path / "main"
    sibling_root = tmp_path / "playlist2"
    main_root.mkdir()
    sibling_root.mkdir()
    (sibling_root / "tag.txt").write_text("감성\n", encoding="utf-8")
    suite = WorkspaceFileToolSuite(main_root)
    registry = suite.build_registry()

    relative_result = await registry.run(ToolCall(tool="workspace_file", arguments={
        "action": "read",
        "path": "../playlist2/tag.txt",
    }))
    absolute_result = await registry.run(ToolCall(tool="workspace_file", arguments={
        "action": "read",
        "path": str(sibling_root / "tag.txt"),
    }))

    assert relative_result["content"] == "감성\n"
    assert absolute_result["content"] == "감성\n"


@pytest.mark.asyncio
async def test_workspace_file_tool_can_delete_file(tmp_path: Path) -> None:
    suite = WorkspaceFileToolSuite(tmp_path)
    registry = suite.build_registry()

    await registry.run(ToolCall(tool="workspace_file", arguments={
        "action": "create",
        "path": "tags.txt",
        "content": "감성\n",
    }))
    delete_result = await registry.run(ToolCall(tool="workspace_file", arguments={
        "action": "delete",
        "path": "tags.txt",
    }))
    read_result = await registry.run(ToolCall(tool="workspace_file", arguments={
        "action": "read",
        "path": "tags.txt",
    }))

    assert delete_result["ok"] is True
    assert read_result["ok"] is False
    assert read_result["error"] == "not_found"


@pytest.mark.asyncio
async def test_terminal_tool_blocks_destructive_command(tmp_path: Path) -> None:
    suite = TerminalToolSuite(tmp_path)
    registry = suite.build_registry()

    with pytest.raises(ValueError):
        await registry.run(ToolCall(tool="terminal_command", arguments={"command": "rm -rf ."}))


@pytest.mark.asyncio
async def test_terminal_tool_result_includes_cwd(tmp_path: Path) -> None:
    suite = TerminalToolSuite(tmp_path)
    registry = suite.build_registry()

    result = await registry.run(ToolCall(tool="terminal_command", arguments={"command": "pwd"}))

    assert Path(result["cwd"]) == tmp_path.resolve()


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

