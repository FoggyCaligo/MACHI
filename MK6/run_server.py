"""MK6 API 서버 실행 스크립트.

사용:
    python MK6/run_server.py
    python MK6/run_server.py --port 8080
    python MK6/run_server.py --host 0.0.0.0 --reload
"""
from __future__ import annotations

import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import uvicorn  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="MK6 API 서버")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="코드 변경 시 자동 재시작")
    args = parser.parse_args()

    uvicorn.run(
        "MK6.app.server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
