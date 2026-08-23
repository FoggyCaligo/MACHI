from MK4.core.agent.prompts import SYSTEM_PROMPT


def test_system_prompt_makes_frozen_required_tools_explicit() -> None:
    assert "frozen_tool_requirements.required_tools was decided before automatic memory recall" in SYSTEM_PROMPT
    assert "minimum set of explicit tool executions required" in SYSTEM_PROMPT
    assert "frozen_tool_requirements.missing_tools is the subset" in SYSTEM_PROMPT
    assert "execute every tool in missing_tools before releasing a final answer" in SYSTEM_PROMPT
    assert "automatic_memory_context is framework context and never counts as execution" in SYSTEM_PROMPT
    assert "Tools outside required_tools remain available" in SYSTEM_PROMPT


def test_system_prompt_makes_read_only_tools_exploratory() -> None:
    assert "Read, search, recall, inspect, and analysis tools are exploratory and low-commitment." in SYSTEM_PROMPT
    assert "You do not need certainty that a read-only tool is necessary before trying it" in SYSTEM_PROMPT
    assert "web/search, persistent memory recall, file/document/image reads, code inspection" in SYSTEM_PROMPT


def test_system_prompt_memory_matches_pre_memory_freeze() -> None:
    assert "automatic_memory_context is partial automatic recall supplied after frozen tool requirements were decided" in SYSTEM_PROMPT
    assert "If recall_memory is listed in frozen_tool_requirements.missing_tools, execute recall_memory" in SYSTEM_PROMPT
    assert "do not use persistent memory as a substitute for current external verification" in SYSTEM_PROMPT


def test_system_prompt_keeps_state_changes_deliberate() -> None:
    assert "State-changing actions are different from exploration." in SYSTEM_PROMPT
    assert "inspect the real target first" in SYSTEM_PROMPT
    assert "then verify the result" in SYSTEM_PROMPT
