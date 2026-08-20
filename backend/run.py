from pathlib import Path

import uvicorn

# The SDK is installed editable from the repo root, so its source sits outside
# backend/. uvicorn's reloader only watches the working directory by default,
# which meant edits to ../vida were invisible until a manual restart.
_HERE = Path(__file__).resolve().parent
_SDK = _HERE.parent / "vida"

if __name__ == "__main__":
    uvicorn.run(
        "api.app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_dirs=[str(_HERE), str(_SDK)],
    )
