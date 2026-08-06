from pathlib import Path

from MK6.language_graph import LanguageGraph


def test_each_turn_creates_new_seq(tmp_path: Path) -> None:
    graph = LanguageGraph(tmp_path / "mk.db")
    first = graph.process("엄마")
    second = graph.process("엄마")
    assert first.input_id != second.input_id
    graph.close()


def test_projection_prefers_repeated_subsequence(tmp_path: Path) -> None:
    graph = LanguageGraph(tmp_path / "mk.db")
    graph.process("엄마")
    graph.process("엄마가 분유 타줄게")
    result = graph.process("엄마는 내일 출장가")
    assert result.segments[0] == "엄마"
    assert result.evidence[0].support == 2
    graph.close()


def test_space_and_punctuation_are_alphs(tmp_path: Path) -> None:
    graph = LanguageGraph(tmp_path / "mk.db")
    result = graph.process("가 .")
    assert result.alphs == ["가", " ", "."]
    graph.close()
