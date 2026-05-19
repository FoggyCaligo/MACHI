from __future__ import annotations

import uvicorn


if __name__ == "__main__":
    uvicorn.run("mk6_1.server:app", host="127.0.0.1", port=8006, reload=True)
