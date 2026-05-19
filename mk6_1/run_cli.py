from __future__ import annotations

import asyncio

from .pipeline import Pipeline


async def main() -> None:
    async with Pipeline() as pipeline:
        while True:
            message = input("you> ").strip()
            if message in {"/q", "/quit", "exit"}:
                break
            if not message:
                continue
            result = await pipeline.run(message)
            print(f"machi> {result.response_text}\n")


if __name__ == "__main__":
    asyncio.run(main())
