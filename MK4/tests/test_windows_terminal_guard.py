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
async def test_command_text_is_passed_to_real_shell_without_preblocking(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    class FakeProcess:
        returncode = 1

        async def communicate(self):
            return b"", b"real shell failure"

        def kill(self):
            pass

    async def fake_subprocess(command, **kwargs):
        seen["command"] = command
        return FakeProcess()

    monkeypatch.setattr(terminal_tools.asyncio, "create_subprocess_shell", fake_subprocess)
    suite = TerminalToolSuite(workspace_root=tmp_path)

    result = await suite._run({"command": "ls -d MK4"})

    assert seen["command"] == "ls -d MK4"
    assert result["ok"] is False
    assert result["returncode"] == 1
    assert "real shell failure" in result["stderr"]
    assert "error" not in result


@pytest.mark.asyncio
async def test_powershell_command_runs_through_same_shell_path(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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


def test_tool_description_allows_system_level_shell_work(tmp_path) -> None:
    registry = TerminalToolSuite(workspace_root=tmp_path).build_registry()
    description = registry.definition("terminal_command").description

    assert "registry" in description.lower()
    assert "startup" in description.lower()
    assert "actual shell/tool execution" in description.lower()
    assert "prefer file_tree" not in description.lower()
    assert "do not use direct unix" not in description.lower()
