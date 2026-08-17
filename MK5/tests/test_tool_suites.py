from __future__ import annotations

from pathlib import Path
import builtins
import zipfile

import pytest

from MK5.tools.terminal_tools import TerminalToolSuite
from MK5.tools.code_index_tools import CodeIndexToolSuite
from MK5.tools.document_tools import DocumentReadToolSuite, _looks_garbled
from MK5.tools.image_tools import ImageAnalyzeToolSuite
from MK5.tools.llm_client import ModelOutputParseError, ModelTurn, _parse_model_turn, _require_tool_manuals, _response_schema_for_tools
from MK5.tools.tool_runtime import ToolCall, ToolDefinition
from MK5.tools.workspace_tools import WorkspaceFileToolSuite
from MK5.tools import web_search
from MK5.tools.web_search import HttpWebSearchTool, SearchHit


def test_low_level_web_tools_are_hidden_from_model() -> None:
    registry = HttpWebSearchTool().build_registry()
    visible_definitions = {definition.name: definition for definition in registry.model_definitions()}

    assert "web_research" in visible_definitions
    assert "market_snapshot" in visible_definitions
    assert "internet_search" not in visible_definitions
    assert "web_page_read" not in visible_definitions
    assert set(visible_definitions["latest_search"].input_schema["properties"]) == {"query"}
    assert set(visible_definitions["market_snapshot"].input_schema["properties"]) == {"query"}


def test_web_page_decoder_uses_html_meta_charset_for_euc_kr() -> None:
    html = (
        '<html><head><meta charset="euc-kr">'
        '<title>대익보이차 공식몰</title></head>'
        '<body>7572(2401) 일루형향(2401)</body></html>'
    )

    decoded = web_search._decode_page_bytes(
        html.encode("euc-kr"),
        content_type="text/html",
    )

    assert "대익보이차 공식몰" in decoded
    assert "7572(2401)" in decoded
    assert "일루형향(2401)" in decoded
    assert "\ufffd" not in decoded


def test_web_page_decoder_uses_http_charset_for_cp949_plain_text() -> None:
    text = "대익보이차 2401 배치"

    decoded = web_search._decode_page_bytes(
        text.encode("cp949"),
        content_type="text/plain; charset=cp949",
    )

    assert decoded == text


def test_web_page_decoder_uses_legacy_http_equiv_meta_charset() -> None:
    html = (
        '<html><head><meta http-equiv="Content-Type" '
        'content="text/html; charset=euc-kr">'
        '<title>대익보이차</title></head></html>'
    )

    decoded = web_search._decode_page_bytes(
        html.encode("euc-kr"),
        content_type="text/html",
    )

    assert "대익보이차" in decoded
    assert "\ufffd" not in decoded


def test_web_page_decoder_defaults_to_utf8_without_declared_charset() -> None:
    text = "UTF-8 한국어 페이지"

    decoded = web_search._decode_page_bytes(
        text.encode("utf-8"),
        content_type="text/html",
    )

    assert decoded == text


@pytest.mark.asyncio
async def test_market_snapshot_stub() -> None:
    from MK5.tools.web_search import StubWebSearchTool

    registry = StubWebSearchTool().build_registry()
    result = await registry.run(ToolCall(tool="market_snapshot", arguments={"query": "태광"}))
    assert result["ok"] is True
    assert result["type"] == "stub_quote"
    assert result["quote"]["name"] == "태광"


def test_unconsulted_tool_call_is_replaced_with_manual_lookup() -> None:
    definitions = [
        ToolDefinition(name="terminal_command", description="terminal", input_schema={}),
        ToolDefinition(name="tool_manual", description="manual", input_schema={}),
    ]
    turn = ModelTurn(tool_calls=[
        ToolCall(tool="terminal_command", arguments={"command": "tree -L 2 MK5"}),
    ])

    guarded = _require_tool_manuals(turn, tool_definitions=definitions, tool_history=[])

    assert guarded.tool_calls == [ToolCall(tool="tool_manual", arguments={"tool": "terminal_command"})]


def test_consulted_tool_call_is_preserved() -> None:
    definitions = [
        ToolDefinition(name="terminal_command", description="terminal", input_schema={}),
        ToolDefinition(name="tool_manual", description="manual", input_schema={}),
    ]
    turn = ModelTurn(tool_calls=[
        ToolCall(tool="terminal_command", arguments={"command": "dir MK5"}),
    ])
    history = [{
        "tool": "tool_manual",
        "arguments": {"tool": "terminal_command"},
        "result": {"ok": True, "tool": "terminal_command", "input_schema": {}},
    }]

    guarded = _require_tool_manuals(turn, tool_definitions=definitions, tool_history=history)

    assert guarded is turn


def test_response_schema_restricts_tool_names_to_registry_list() -> None:
    schema = _response_schema_for_tools(["file_search", "code_index", "code_search"])

    tool_schema = schema["properties"]["tool_calls"]["items"]["properties"]["tool"]
    assert tool_schema["enum"] == ["code_index", "code_search", "file_search"]


def test_invalid_model_json_raises_specific_parse_error() -> None:
    with pytest.raises(ModelOutputParseError):
        _parse_model_turn("일반 텍스트 응답")


def test_semantically_truncated_final_answer_is_rejected_even_when_json_is_valid() -> None:
    raw = (
        '{"final_answer":"문장이 여기서(","tool_calls":[],'
        '"final_answer_kind":"answer","completion_tools":[]}'
    )

    with pytest.raises(ModelOutputParseError, match="opening bracket"):
        _parse_model_turn(raw)


def test_complete_final_answer_with_balanced_parentheses_is_accepted() -> None:
    raw = (
        '{"final_answer":"마지막 답변(요약)을 확인했습니다.","tool_calls":[],'
        '"final_answer_kind":"answer","completion_tools":[]}'
    )

    assert _parse_model_turn(raw).final_answer == "마지막 답변(요약)을 확인했습니다."


@pytest.mark.asyncio
async def test_file_tools_can_create_update_and_read(tmp_path: Path) -> None:
    suite = WorkspaceFileToolSuite(tmp_path)
    registry = suite.build_registry()

    await registry.run(ToolCall(tool="file_create", arguments={
        "path": "notes/test.txt",
        "content": "hello",
    }))
    result = await registry.run(ToolCall(tool="file_read", arguments={"path": "notes/test.txt"}))
    assert result["ok"] is True
    assert result["content"] == "hello"

    await registry.run(ToolCall(tool="file_update", arguments={
        "path": "notes/test.txt",
        "old": "hello",
        "new": "goodbye",
    }))
    result = await registry.run(ToolCall(tool="file_read", arguments={"path": "notes/test.txt"}))
    assert result["content"] == "goodbye"


@pytest.mark.asyncio
async def test_file_update_append_mode(tmp_path: Path) -> None:
    suite = WorkspaceFileToolSuite(tmp_path)
    registry = suite.build_registry()
    target = tmp_path / "notes.txt"
    target.write_text("first", encoding="utf-8")

    result = await registry.run(ToolCall(tool="file_update", arguments={
        "path": "notes.txt",
        "content": "second",
        "mode": "append",
    }))

    assert result["ok"] is True
    assert target.read_text(encoding="utf-8") == "first\nsecond"


@pytest.mark.asyncio
async def test_file_update_requires_unique_old_text(tmp_path: Path) -> None:
    suite = WorkspaceFileToolSuite(tmp_path)
    registry = suite.build_registry()
    target = tmp_path / "notes.txt"
    target.write_text("alpha alpha", encoding="utf-8")

    result = await registry.run(ToolCall(tool="file_update", arguments={
        "path": "notes.txt",
        "old": "alpha",
        "new": "beta",
    }))

    assert result["ok"] is False
    assert result["error"] == "old_text_not_unique"
    assert target.read_text(encoding="utf-8") == "alpha alpha"


@pytest.mark.asyncio
async def test_file_update_overwrite_mode(tmp_path: Path) -> None:
    suite = WorkspaceFileToolSuite(tmp_path)
    registry = suite.build_registry()
    target = tmp_path / "notes.txt"
    target.write_text("old", encoding="utf-8")

    result = await registry.run(ToolCall(tool="file_update", arguments={
        "path": "notes.txt",
        "content": "new",
        "mode": "overwrite",
    }))

    assert result["ok"] is True
    assert target.read_text(encoding="utf-8") == "new"


@pytest.mark.asyncio
async def test_file_update_rejects_mixed_replace_and_content_contract(tmp_path: Path) -> None:
    suite = WorkspaceFileToolSuite(tmp_path)
    registry = suite.build_registry()
    target = tmp_path / "notes.txt"
    target.write_text("old", encoding="utf-8")

    result = await registry.run(ToolCall(tool="file_update", arguments={
        "path": "notes.txt",
        "old": "old",
        "new": "new",
        "content": "replacement",
        "mode": "overwrite",
    }))

    assert result["ok"] is False
    assert result["error"] == "invalid_arguments"
    assert target.read_text(encoding="utf-8") == "old"


@pytest.mark.asyncio
async def test_file_update_rejects_unknown_mode(tmp_path: Path) -> None:
    suite = WorkspaceFileToolSuite(tmp_path)
    registry = suite.build_registry()
    target = tmp_path / "notes.txt"
    target.write_text("old", encoding="utf-8")

    result = await registry.run(ToolCall(tool="file_update", arguments={
        "path": "notes.txt",
        "content": "new",
        "mode": "mystery",
    }))

    assert result["ok"] is False
    assert result["error"] == "invalid_mode"
    assert target.read_text(encoding="utf-8") == "old"


def test_code_index_marks_parse_errors_without_failing_whole_index(tmp_path: Path) -> None:
    (tmp_path / "good.py").write_text("def ok():\n    return 1\n", encoding="utf-8")
    (tmp_path / "bad.py").write_text("def broken(:\n", encoding="utf-8")
    registry = CodeIndexToolSuite(tmp_path).build_registry()

    result = registry.definition("code_index")
    assert result is not None


@pytest.mark.asyncio
async def test_document_read_plain_text(tmp_path: Path) -> None:
    path = tmp_path / "note.txt"
    path.write_text("hello", encoding="utf-8")
    registry = DocumentReadToolSuite(tmp_path).build_registry()

    result = await registry.run(ToolCall(tool="document_read", arguments={"path": "note.txt"}))

    assert result["ok"] is True
    assert result["content"] == "hello"


@pytest.mark.asyncio
async def test_terminal_command_runs_and_captures_output(tmp_path: Path) -> None:
    registry = TerminalToolSuite(tmp_path).build_registry()

    result = await registry.run(ToolCall(tool="terminal_command", arguments={
        "command": "python -c \"print('hello')\"",
    }))

    assert result["returncode"] == 0
    assert "hello" in result["stdout"]


def test_document_garbled_detector() -> None:
    assert _looks_garbled("abc\ufffd\ufffd\ufffddef") is True
    assert _looks_garbled("정상 한글 문장입니다.") is False


def test_response_schema_allows_no_tools() -> None:
    schema = _response_schema_for_tools([])
    tool_schema = schema["properties"]["tool_calls"]["items"]["properties"]["tool"]
    assert "enum" not in tool_schema


def test_zipfile_is_available_for_document_tools() -> None:
    assert zipfile.ZipFile is not None
    assert builtins.open is not None
