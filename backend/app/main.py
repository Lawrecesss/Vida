import os
import shutil
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from vida import Transcript, VidaError, transcribe

app = FastAPI(title="Vida backend")

# The browser calls this service directly, so CORS names the page's origin;
# never "*".
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_methods=["POST"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/generate", response_model=Transcript)
async def generate(video: UploadFile = File(...), model: str | None = Form(None)) -> Transcript:
    suffix = Path(video.filename or "").suffix or ".bin"
    with tempfile.TemporaryDirectory() as scratch:
        path = Path(scratch) / f"upload{suffix}"
        with path.open("wb") as f:
            shutil.copyfileobj(video.file, f)
        try:
            return await transcribe(path, model=model or None)
        except VidaError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
