from __future__ import annotations

import uvicorn


if __name__ == "__main__":
    uvicorn.run("MK6.app.server:app", host="127.0.0.1", port=8060, reload=False)
