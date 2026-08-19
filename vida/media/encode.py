"""Base64 helpers for inlining media into model requests."""

from __future__ import annotations

import base64

__all__ = ["encode_file", "data_url"]


def encode_file(path: str) -> str:
    """Base64-encode a file's bytes."""
    with open(path, "rb") as handle:
        return base64.b64encode(handle.read()).decode("utf-8")


def data_url(path: str, mime: str) -> str:
    """Build an RFC 2397 data URL for a local file."""
    return f"data:{mime};base64,{encode_file(path)}"
