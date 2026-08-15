from __future__ import annotations

from pathlib import Path

import pytest

from MK5.tools.terminal_tools import TerminalToolSuite
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


def test_search_query_is_reduced_to_concept_nodes() -> None:
    assert web_search._query_nodes("글록의 특징과 총기시장에서의 의의") == ["글록"]


@pytest.mark.asyncio
async def test_internet_search_runs_per_concept_node(monkeypatch: pytest.MonkeyPatch) -> None:
    searched: list[tuple[str, str]] = []

    async def fake_ddg(query: str) -> list[SearchHit]:
        searched.append(("ddg", query))
        return [SearchHit(title=f"{query}-ddg", url=f"https://example.com/{query}/ddg", snippet="result", source="duckduckgo")]

    async def fake_wiki(query: str, lang: str) -> list[SearchHit]:
        searched.append((f"wiki_{lang}", query))
        return [SearchHit(title=f"{query}-{lang}", url=f"https://example.com/{query}/{lang}", snippet="result", source=f"wikipedia_{lang}")]

    monkeypatch.setattr(web_search, "_ddg_search", fake_ddg)
    monkeypatch.setattr(web_search, "_wiki_search", fake_wiki)

    result = await HttpWebSearchTool()._run({"query": "파이썬 러스트 비교"})

    assert result["search_nodes"] == ["파이썬", "러스트"]
    assert {item["query_node"] for item in result["results"]} == {"파이썬", "러스트"}
    assert ("ddg", "파이썬") in searched
    assert ("wiki_ko", "러스트") in searched

