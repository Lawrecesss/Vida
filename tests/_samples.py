"""Locating the sample media that some tests need.

``vids/**`` is tracked in Git LFS. A clone without ``git lfs pull`` still leaves
a file at that path — a ~130 byte text pointer rather than the media. Gating on
``os.path.exists`` therefore lets those tests run against the pointer and fail
inside ffmpeg with a confusing MediaError, which is exactly what happened on CI.
Check the content, not the path.
"""

from __future__ import annotations

import os

__all__ = ["sample_path", "sample_available"]

_LFS_POINTER = b"version https://git-lfs.github.com/spec/v1"


def sample_path(name: str) -> str:
    """Absolute path to a file in ``vids/``, whether or not it is fetched."""
    return os.path.join(os.path.dirname(__file__), "..", "vids", name)


def sample_available(path: str) -> bool:
    """True only when ``path`` holds real media rather than an LFS pointer."""
    if not os.path.isfile(path):
        return False
    try:
        with open(path, "rb") as handle:
            return not handle.read(len(_LFS_POINTER)).startswith(_LFS_POINTER)
    except OSError:
        return False
