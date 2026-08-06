from __future__ import annotations

import argparse
import json
from pathlib import Path

from .language_graph import LanguageGraph


def input_to_list(text: str, db_path: str | Path = "MK/data/mk_language.db") -> list[str]:
    """입력 문장을 언어 그래프로 처리하고 segment 리스트만 반환한다."""
    graph = LanguageGraph(db_path)
    try:
        return graph.process(text).segments
    finally:
        graph.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="문장을 alph → seq → proj 과정으로 처리해 segment 리스트로 출력합니다."
    )
    parser.add_argument("text", nargs="?", help="처리할 문장. 생략하면 터미널에서 입력받습니다.")
    parser.add_argument(
        "--db",
        default="MK/data/mk_language.db",
        help="언어 그래프 SQLite 파일 경로",
    )
    args = parser.parse_args()

    text = args.text if args.text is not None else input("입력: ")
    segments = input_to_list(text, args.db)
    print(json.dumps(segments, ensure_ascii=False))


if __name__ == "__main__":
    main()
