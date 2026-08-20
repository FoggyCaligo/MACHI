"""MK4 CLI."""
from __future__ import annotations

import asyncio
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from MK4.app.pipeline import Pipeline  # noqa: E402


async def main() -> None:
    print("MK4 CLI - enter 'exit' to quit.")
    print("-" * 40)

    async with Pipeline() as pipeline:
        while True:
            try:
                user_input = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nExiting.")
                break

            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit"):
                print("Exiting.")
                break

            try:
                result = await pipeline.run(user_input)
                print(f"MK4: {result.response_text}")
                c = result.conclusion
                print(
                    f"     [loops={c.loop_count} | nodes={len(c.nodes)} | "
                    f"edges={len(c.edges)} | empty_slots={c.had_empty_slots}]"
                )
            except Exception as exc:
                print(f"[error] {exc}")


if __name__ == "__main__":
    asyncio.run(main())

