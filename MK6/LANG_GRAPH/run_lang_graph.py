from __future__ import annotations

import argparse
import json
from pathlib import Path

from .lang_graph import DEFAULT_DB_PATH, segment_text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="LANG_GRAPH에 문장을 넣고 segment 리스트를 확인합니다."
    )
    parser.add_argument(
        "text",
        nargs="?",
        help="분해할 문자열. 생략하면 프롬프트로 입력받습니다.",
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help="사용할 SQLite DB 경로",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    text = args.text if args.text is not None else input("text> ")
    segments = segment_text(text, db_path=Path(args.db))
    print(json.dumps(segments, ensure_ascii=False))


if __name__ == "__main__":
    main()
