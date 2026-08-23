from __future__ import annotations

import sys

from .. import config


def log_timing(stage: str, elapsed_seconds: float, **fields: object) -> None:
    """Emit one structured timing line when agent debug logging is enabled."""
    if not config.AGENT_DEBUG_LOG:
        return
    suffix = " ".join(
        f"{key}={value}"
        for key, value in fields.items()
        if value is not None
    )
    message = f"[MK4 timing] stage={stage} elapsed={elapsed_seconds:.2f}s"
    if suffix:
        message = f"{message} {suffix}"
    print(message, file=sys.stderr, flush=True)
