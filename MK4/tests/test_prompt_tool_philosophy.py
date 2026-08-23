from MK4.core.agent.prompts import SYSTEM_PROMPT


def test_system_prompt_makes_read_only_tools_exploratory() -> None:
    assert "Read, search, recall, inspect, and analysis tools are exploratory and low-commitment." in SYSTEM_PROMPT
    assert "You do not need certainty that a read-only tool is necessary before trying it" in SYSTEM_PROMPT
    assert "web/search, persistent memory recall, file/document/image reads, code inspection" in SYSTEM_PROMPT


def test_system_prompt_keeps_state_changes_deliberate() -> None:
    assert "State-changing actions are different from exploration." in SYSTEM_PROMPT
    assert "inspect the real target first" in SYSTEM_PROMPT
    assert "then verify the result" in SYSTEM_PROMPT
