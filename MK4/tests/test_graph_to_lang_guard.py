from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from MK4.app.pipeline import _extract_final_answer, _is_answer_grounded
from MK4.core.verbalization.answer_contract_clean import (
    AnswerContract,
    SurfaceFocus,
    SurfaceGraphSection,
    SurfaceInput,
    SurfaceResponse,
)


def _make_contract() -> AnswerContract:
    return AnswerContract(
        contract_type="surface_frame",
        source="test",
        input=SurfaceInput(text="이 프로젝트에 대해서, 넌 어떻게 생각해?"),
        response=SurfaceResponse(continuity="shifted_topic", max_sentences=4),
        input_graph=SurfaceGraphSection(
            speaker="user",
            focus=SurfaceFocus(primary=["프로젝트", "그래프"], supporting=["기억"]),
        ),
        conclusion_graph=SurfaceGraphSection(
            speaker="system",
            focus=SurfaceFocus(primary=["장기기억"], supporting=["세계모델"]),
        ),
        search_graph=SurfaceGraphSection(
            speaker="external",
            focus=SurfaceFocus(primary=["업데이트"], supporting=[]),
        ),
    )


class GraphToLangGuardTest(unittest.TestCase):
    def test_extracts_valid_structured_answer(self) -> None:
        payload = '{"final_answer": "사용자께서 신재용이라고 말씀하셨네요. 반갑습니다."}'
        self.assertEqual(
            _extract_final_answer(payload),
            "사용자께서 신재용이라고 말씀하셨네요. 반갑습니다.",
        )

    def test_rejects_non_json_meta_text(self) -> None:
        payload = """
다음은 제공된 SurfaceFrame JSON 데이터를 바탕으로 생성된 자연스러운 한국어 답변입니다.
전체적인 맥락:
- 신재용과 여러 개념이 연결되어 있습니다.
"""
        self.assertIsNone(_extract_final_answer(payload))

    def test_extracts_fenced_json_answer(self) -> None:
        payload = """
```json
{"final_answer": "글록은 오스트리아 권총 브랜드입니다."}
```
"""
        self.assertEqual(
            _extract_final_answer(payload),
            "글록은 오스트리아 권총 브랜드입니다.",
        )

    def test_accepts_grounded_plain_answer_when_json_missing(self) -> None:
        payload = "글록은 오스트리아 기업 글록이 만든 권총 계열로, 1980년대부터 널리 보급되었습니다."
        self.assertEqual(
            _extract_final_answer(payload),
            "글록은 오스트리아 기업 글록이 만든 권총 계열로, 1980년대부터 널리 보급되었습니다.",
        )

    def test_accepts_grounded_answer(self) -> None:
        contract = _make_contract()
        answer = "이 프로젝트는 그래프 기반 장기기억으로 세계모델을 계속 업데이트한다는 점이 인상적이에요."
        self.assertTrue(_is_answer_grounded(answer, contract))

    def test_rejects_ungrounded_followup_answer(self) -> None:
        contract = _make_contract()
        answer = "알겠습니다. 어떤 도움이 필요하신가요?"
        self.assertFalse(_is_answer_grounded(answer, contract))

    def test_rejects_short_low_information_answer(self) -> None:
        contract = _make_contract()
        answer = "반갑습니다."
        self.assertFalse(_is_answer_grounded(answer, contract))


if __name__ == "__main__":
    unittest.main()

