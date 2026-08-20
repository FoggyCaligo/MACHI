from __future__ import annotations

import pytest

from MK4.tools import terminal_tools
from MK4.tools.terminal_tools import TerminalToolSuite, _decode_process_output


def test_decode_process_output_keeps_utf8(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(terminal_tools, "_is_windows", lambda: True)
    text = "안녕하세요 UTF-8"
    assert _decode_process_output(text.encode("utf-8")) == text


def test_decode_process_output_recovers_cp949(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(terminal_tools, "_is_windows", lambda: True)
    monkeypatch.setattr(terminal_tools.locale, "getpreferredencoding", lambda _do_setlocale=False: "utf-8")
    text = "'ls'은(는) 내부 또는 외부 명령, 실행할 수 있는 프로그램, 또는 배치 파일이 아닙니다."
    assert _decode_process_output(text.encode("cp949")) == text


@pytest.mark.asyncio
async def test_windows_ls_is_blocked_before_subprocess(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(terminal_tools, "_is_windows", lambda: True)
    called = False

    async def fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("subprocess should not run for blocked Unix command")

    monkeypatch.setattr(terminal_tools.asyncio, "create_subprocess_shell", fail_if_called)
    suite = TerminalToolSuite(workspace_root=tmp_path)

    result = await suite._run({"command": "ls -d MK4"})

    assert result["ok"] is False
    assert result["error"] == "unsupported_windows_shell_command"
    assert result["recovery"]["prefer_file_tree"] is True
    assert result["recovery"]["next_tools"][0] == "file_tree"
    assert called is False


@pytest.mark.asyncio
async def test_windows_cat_is_blocked_without_file_tree_preference(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(terminal_tools, "_is_windows", lambda: True)
    suite = TerminalToolSuite(workspace_root=tmp_path)

    result = await suite._run({"command": "cat README.md"})

    assert result["ok"] is False
    assert result["error"] == "unsupported_windows_shell_command"
    assert result["recovery"]["prefer_file_tree"] is False
    assert result["recovery"]["next_tools"] == ["terminal_command"]


@pytest.mark.asyncio
async def test_powershell_command_is_not_misclassified_as_direct_unix(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(terminal_tools, "_is_windows", lambda: True)

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return "MK4\r\n".encode("utf-8"), b""

        def kill(self):
            pass

    async def fake_subprocess(*args, **kwargs):
        return FakeProcess()

    monkeypatch.setattr(terminal_tools.asyncio, "create_subprocess_shell", fake_subprocess)
    suite = TerminalToolSuite(workspace_root=tmp_path)

    result = await suite._run({"command": "powershell -NoProfile -Command \"Get-ChildItem\""})

    assert result["ok"] is True
    assert result["returncode"] == 0
    assert "MK4" in result["stdout"]


def test_tool_description_prefers_file_tree_for_directory_discovery(tmp_path) -> None:
    registry = TerminalToolSuite(workspace_root=tmp_path).build_registry()
    description = registry.definition("terminal_command").description

    assert "prefer file_tree" in description.lower()
    assert "ls" in description
    assert "Windows cmd.exe" in description
