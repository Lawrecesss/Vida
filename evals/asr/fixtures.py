"""Loading the accuracy fixtures: media paired with a hand-corrected reference.

A fixture is one clip plus the transcript a human agreed it says. The media is
deliberately *not* committed — movie clips are copyrighted — so a manifest entry
whose media is missing is skipped with a note rather than failing the run. The
reference ``.srt`` files are text and do belong in the repo: they are the part
that took the work.

Deliberately separate from ``tests/_samples.py``. That fetches ``vids/test2.mp4``,
a generic action-camera clip used to exercise the pipeline's plumbing; mixing
it in here would conflate CI fixtures with accuracy fixtures and quietly move
the WER number for reasons that have nothing to do with accuracy.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

__all__ = ["Fixture", "load_manifest", "read_reference"]

_TIMECODE = "-->"


@dataclass(frozen=True)
class Fixture:
    """One clip and the transcript it is known to contain."""

    id: str
    media: str
    reference: str
    kind: str = "dialogue"
    """What this clip is meant to stress: quiet dialogue, music bed, accents, names."""

    language: str | None = None
    """Passed to ASR as the language hint. Pin it — detection is a separate variable."""

    glossary: list[str] | None = None
    """Character names and invented vocabulary, for measuring stream 3's effect."""

    notes: str = ""

    @property
    def available(self) -> bool:
        """True when both halves of the pair are actually on disk."""
        return os.path.isfile(self.media) and os.path.isfile(self.reference)


def load_manifest(path: str) -> list[Fixture]:
    """Read a manifest file into fixtures, resolving paths relative to it.

    Relative paths in the manifest resolve against the manifest's own directory,
    so a checkout can be moved without editing it.
    """
    with open(path, encoding="utf-8") as handle:
        raw = json.load(handle)

    root = os.path.dirname(os.path.abspath(path))

    def _resolve(value: str) -> str:
        return value if os.path.isabs(value) else os.path.normpath(os.path.join(root, value))

    fixtures = []
    for entry in raw:
        fixtures.append(
            Fixture(
                id=entry["id"],
                media=_resolve(entry["media"]),
                reference=_resolve(entry["reference"]),
                kind=entry.get("kind", "dialogue"),
                language=entry.get("language"),
                glossary=entry.get("glossary"),
                notes=entry.get("notes", ""),
            )
        )
    return fixtures


def read_reference(path: str) -> str:
    """Extract the spoken text from a reference ``.srt`` or ``.txt``.

    WER scores joined text, so the timestamps are dropped here rather than
    being held to frame accuracy in the reference — which is what makes
    hand-correcting a reference affordable in the first place.
    """
    with open(path, encoding="utf-8-sig") as handle:
        body = handle.read()

    if os.path.splitext(path)[1].lower() not in {".srt", ".vtt"}:
        return body

    lines = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.isdigit() or _TIMECODE in stripped:
            continue
        if stripped.upper().startswith(("WEBVTT", "NOTE ")):
            continue
        lines.append(stripped)
    return " ".join(lines)
