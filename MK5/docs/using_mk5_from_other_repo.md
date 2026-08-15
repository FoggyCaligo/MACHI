# Using MK5 from another repository

`MK5` can be used as a graph-memory and tool-orchestration engine from another repository, such as `playlist2`.

The important point is that the host repository should own its workspace and memory files. `MK5` should provide the agent pipeline, graph memory, and tools.

## Recommended shape

```text
playlist2/
├── app/
├── data/
├── .machi/
│   ├── memory.db
│   └── sentence_breaker.db
└── playlist_agent.py
```

## Install MACHI for import

From the host repository, install MACHI as an editable dependency:

```powershell
pip install -e C:\Users\bigla\Documents\Git\MACHI
```

Alternatively, add MACHI as a submodule or vendor directory and make sure the host Python process can import `MK5`.

## Host-specific environment

Set these before creating the `Pipeline`.

```powershell
$env:MK5_WORKSPACE_ROOT="C:\Users\bigla\Documents\Git\playlist2"
$env:MK5_DB_PATH="C:\Users\bigla\Documents\Git\playlist2\.machi\memory.db"
$env:MK5_SENTENCE_BREAKER_DB_PATH="C:\Users\bigla\Documents\Git\playlist2\.machi\sentence_breaker.db"
```

### What each path means

- `MK5_WORKSPACE_ROOT`: the root that `workspace_file` and `terminal_command` operate inside.
- `MK5_DB_PATH`: the graph-memory SQLite database for this host project.
- `MK5_SENTENCE_BREAKER_DB_PATH`: the Sentence_Breaker database for this host project.

Keeping these paths inside the host repository gives each project its own memory and file scope.

## Minimal Python usage

```python
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MACHI_DIR = ROOT / ".machi"
MACHI_DIR.mkdir(exist_ok=True)

os.environ.setdefault("MK5_WORKSPACE_ROOT", str(ROOT))
os.environ.setdefault("MK5_DB_PATH", str(MACHI_DIR / "memory.db"))
os.environ.setdefault("MK5_SENTENCE_BREAKER_DB_PATH", str(MACHI_DIR / "sentence_breaker.db"))

from MK5.app.pipeline import Pipeline


async def ask_mk5(user_id: str, message: str):
    pipeline = Pipeline()
    try:
        return await pipeline.run(
            user_id=user_id,
            session_id="playlist2",
            message=message,
        )
    finally:
        pipeline.close()
```

## Notes

- Create or set the environment variables before importing modules that read `MK5.config`.
- Use a stable `user_id` if the host app wants long-term user memory.
- Use a stable `session_id` when a host app wants short-term conversational continuity.
- `workspace_file` is scoped to `MK5_WORKSPACE_ROOT` and rejects paths that escape it.
- `terminal_command` also runs inside `MK5_WORKSPACE_ROOT`.
