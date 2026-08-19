"""Shared application state: one SDK client for the process."""

from __future__ import annotations

import os
import re
import uuid

from fastapi import HTTPException

from vida import Vida

UPLOAD_DIR = os.path.abspath(os.getenv("VIDA_UPLOAD_DIR", "/tmp/vida_uploads"))
os.makedirs(UPLOAD_DIR, exist_ok=True)

MAX_UPLOAD_MB = float(os.getenv("VIDA_MAX_UPLOAD_MB", "1024"))

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")

_client: Vida | None = None


def get_vida() -> Vida:
    """The process-wide SDK client, so HTTP connections are pooled across requests."""
    global _client
    if _client is None:
        _client = Vida()
    return _client


async def close_vida() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def safe_upload_name(filename: str | None) -> str:
    """Build a collision-free, traversal-proof name for an uploaded file.

    The client controls this string, so the directory component is discarded
    entirely and a UUID prefix is added rather than trusting it to be unique.
    """
    base = os.path.basename(filename or "upload")
    base = _UNSAFE.sub("_", base).lstrip(".") or "upload"
    return f"{uuid.uuid4().hex[:12]}_{base[:120]}"


def resolve_upload(video_path: str) -> str:
    """Validate a client-supplied path and return it resolved.

    Requests carry back the path returned by ``/upload``. Without this check a
    caller could name any file on the host and have the server read it.
    """
    if not video_path:
        raise HTTPException(status_code=400, detail="video_path is required")

    resolved = os.path.realpath(video_path)
    root = os.path.realpath(UPLOAD_DIR)

    if os.path.commonpath([resolved, root]) != root:
        raise HTTPException(
            status_code=400,
            detail="video_path must refer to a file uploaded through /upload",
        )
    if not os.path.isfile(resolved):
        raise HTTPException(status_code=404, detail="Uploaded file not found or already cleaned up")

    return resolved
