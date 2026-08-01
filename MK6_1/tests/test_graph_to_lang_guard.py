from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from MK6_1.app.pipeline import _extract_final_answer


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


if __name__ == "__main__":
    unittest.main()
