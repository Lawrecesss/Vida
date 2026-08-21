"""Transcript translation.

The hard part isn't translating text, it's keeping each translated line glued
to the timestamp it came from. Segments go out in numbered batches, come back
with the same numbers, and get reattached by id — so subtitles still line up
with the video afterwards.

Batches are translated concurrently, which is what keeps a two-hour transcript
in the seconds-to-a-minute range rather than minutes.
"""

from __future__ import annotations

import asyncio
import re

from vida.config import TranslationConfig
from vida.errors import TranslationError
from vida.llm import OpenRouterClient, strip_reasoning
from vida.types import Segment, Transcript

__all__ = ["translate_transcript", "translate_text"]

_SEGMENT_RE = re.compile(r"<s\s+id=\"?(\d+)\"?\s*>(.*?)</s>", re.DOTALL)

_SYSTEM = (
    "You are a professional subtitle translator. You translate spoken-language "
    "transcripts while preserving meaning, register, and tone."
)

_INSTRUCTIONS = """Translate every segment below into {target}.

Rules:
- Output EXACTLY one <s id="N">...</s> line per input segment, reusing the same id.
- Do not merge, split, reorder, drop, or add segments.
- Translate the meaning, not word-for-word. Keep it natural and idiomatic in {target}.
- These are subtitles: keep each line about as long as the original so it stays readable on screen.
- Preserve proper nouns, numbers, and technical terms unless {target} has a standard equivalent.
- If a segment is already in {target}, repeat it unchanged.
- Output only the <s> lines. No preamble, no notes, no explanation.

Segments:
{segments}"""


def _source_note(segments: list[Segment], fallback: str | None) -> str:
    """Describe what the batch is actually in.

    Telling the model "the source language is English" when half the batch is
    Burmese is worse than saying nothing: it invites the model to treat the
    Burmese as garbled English and "fix" it. Per-segment languages let a mixed
    batch be named honestly instead.
    """
    present = []
    for segment in segments:
        if segment.language and segment.language not in present:
            present.append(segment.language)

    if len(present) == 1:
        return f"The source language is {present[0]}. "
    if len(present) > 1:
        joined = ", ".join(present)
        return (
            f"The source segments are a mix of these languages: {joined}. "
            "Translate each one from whichever language it is actually in. "
        )
    return f"The source language is {fallback}. " if fallback else ""


def _render(segments: list[Segment]) -> str:
    return "\n".join(f'<s id="{s.id}">{s.text.strip()}</s>' for s in segments)


def _parse(response: str) -> dict[int, str]:
    """Pull ``id -> translated text`` out of a model response."""
    return {
        int(match.group(1)): match.group(2).strip()
        for match in _SEGMENT_RE.finditer(response)
    }


async def _translate_batch(
    client: OpenRouterClient,
    batch: list[Segment],
    target_language: str,
    config: TranslationConfig,
    source_language: str | None,
) -> dict[int, str]:
    """Translate one batch, degrading to per-segment calls if alignment breaks."""
    source_note = _source_note(batch, source_language)
    prompt = source_note + _INSTRUCTIONS.format(
        target=target_language, segments=_render(batch)
    )

    raw = await client.complete(
        prompt,
        model=config.model,
        temperature=config.temperature,
        system=_SYSTEM,
        timeout=config.timeout,
    )
    translated = _parse(strip_reasoning(raw))

    missing = [segment for segment in batch if segment.id not in translated]
    if not missing:
        return translated

    # A model that dropped or merged lines can usually still handle them one at
    # a time; falling back per-segment is slower but keeps the timeline intact.
    recovered = await asyncio.gather(
        *(
            _translate_single(client, segment, target_language, config, source_language)
            for segment in missing
        ),
        return_exceptions=True,
    )
    for segment, result in zip(missing, recovered, strict=True):
        # Last resort: keep the original text so the subtitle track has no holes.
        translated[segment.id] = (
            result if isinstance(result, str) and result else segment.text
        )

    return translated


async def _translate_single(
    client: OpenRouterClient,
    segment: Segment,
    target_language: str,
    config: TranslationConfig,
    source_language: str | None,
) -> str:
    prompt = (
        f"Translate this subtitle line into {target_language}. "
        f"Output only the translation, with no quotes or commentary.\n\n{segment.text.strip()}"
    )
    raw = await client.complete(
        prompt,
        model=config.model,
        temperature=config.temperature,
        system=_SYSTEM,
        timeout=config.timeout,
    )
    return strip_reasoning(raw).strip().strip('"')


async def translate_transcript(
    transcript: Transcript,
    target_language: str,
    *,
    client: OpenRouterClient,
    config: TranslationConfig | None = None,
) -> Transcript:
    """Translate a transcript into ``target_language``, timestamps intact.

    Args:
        transcript: The transcript to translate.
        target_language: Target language name or code, e.g. ``"Spanish"`` or ``"es"``.
        client: An OpenRouter client to run the calls on.
        config: Batch size, concurrency, and model overrides.

    Returns:
        A new :class:`~vida.types.Transcript` with the same segment ids, start
        and end times, and the text translated.
    """
    config = config or TranslationConfig()

    if not transcript.segments:
        return Transcript(
            language=target_language,
            segments=[],
            duration=transcript.duration,
            source=transcript.source,
            backend=transcript.backend,
        )

    batches = [
        transcript.segments[i : i + config.batch_size]
        for i in range(0, len(transcript.segments), config.batch_size)
    ]
    semaphore = asyncio.Semaphore(max(config.concurrency, 1))

    async def _run(batch: list[Segment]) -> dict[int, str]:
        async with semaphore:
            return await _translate_batch(
                client, batch, target_language, config, transcript.language
            )

    # Keeping a bilingual recording's segments in source order means a batch is
    # usually all one language, and the few batches that straddle the switch
    # are told so explicitly rather than being mislabelled.

    try:
        results = await asyncio.gather(*(_run(batch) for batch in batches))
    except Exception as exc:
        raise TranslationError(f"Translation to {target_language!r} failed: {exc}") from exc

    translations: dict[int, str] = {}
    for result in results:
        translations.update(result)

    return Transcript(
        language=target_language,
        segments=[
            Segment(
                id=segment.id,
                start=segment.start,
                end=segment.end,
                text=translations.get(segment.id, segment.text),
                speaker=segment.speaker,
                confidence=segment.confidence,
                # Every segment is in the target language now; carrying the
                # source language forward would make the output claim to be
                # something it is not.
                language=target_language,
            )
            for segment in transcript.segments
        ],
        duration=transcript.duration,
        source=transcript.source,
        backend=transcript.backend,
    )


async def translate_text(
    text: str,
    target_language: str,
    *,
    client: OpenRouterClient,
    config: TranslationConfig | None = None,
) -> str:
    """Translate a plain block of text (a summary, a title, a description)."""
    config = config or TranslationConfig()
    if not text.strip():
        return ""

    raw = await client.complete(
        f"Translate the following text into {target_language}. Preserve the formatting "
        f"and structure. Output only the translation.\n\n{text}",
        model=config.model,
        temperature=config.temperature,
        system=_SYSTEM,
        timeout=config.timeout,
    )
    return strip_reasoning(raw).strip()
