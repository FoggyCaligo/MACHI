"""MK6 대화형 CLI.

사용:
    python MK6/run_cli.py          # D:\git\MACHI\ 에서 실행
    python run_cli.py              # MK6\ 안에서 실행

종료: 'exit' 또는 Ctrl-C
"""
from __future__ import annotations

import asyncio
import os
import sys

# 이 스크립트가 어디서 실행되든 MK6 패키지를 찾을 수 있도록
# 스크립트 위치 기준으로 부모 디렉터리(D:\git\MACHI\)를 path에 추가한다.
_HERE = os.path.dirname(os.path.abspath(__file__))          # MK6/
_ROOT = os.path.dirname(_HERE)                              # MACHI/
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from MK6.app.pipeline import Pipeline  # noqa: E402


async def main() -> None:
    print("MK6 CLI — 'exit'를 입력하면 종료합니다.")
    print("-" * 40)

    async with Pipeline() as pipeline:
        while True:
            try:
                user_input = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n종료합니다.")
                break

            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit", "종료"):
                print("종료합니다.")
                break

            try:
                result = await pipeline.run(user_input)
                print(f"MK6: {result.response_text}")
                c = result.conclusion
                print(
                    f"     [루프 {c.loop_count}회 | 노드 {len(c.nodes)} | "
                    f"엣지 {len(c.edges)} | EmptySlot {'있음' if c.had_empty_slots else '없음'}]"
                )
            except Exception as exc:
                print(f"[오류] {exc}")


if __name__ == "__main__":
    asyncio.run(main())
