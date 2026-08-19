"""Translation keeps text glued to its timestamps."""

from vida.config import TranslationConfig
from vida.translate.core import _parse, translate_transcript
from vida.types import Segment, Transcript


class FakeLLM:
    """Stands in for OpenRouterClient, echoing a scripted response shape."""

    def __init__(self, behaviour="ok"):
        self.behaviour = behaviour
        self.calls = 0
        self.batch_sizes = []

    async def complete(self, prompt, **kwargs):
        self.calls += 1
        import re

        ids = re.findall(r'<s id="(\d+)">(.*?)</s>', prompt, re.DOTALL)

        if not ids:  # the per-segment fallback prompt has no <s> markers
            return "SINGLE"

        self.batch_sizes.append(len(ids))

        if self.behaviour == "drops_one":
            ids = ids[:-1]
        elif self.behaviour == "reordered":
            ids = list(reversed(ids))
        elif self.behaviour == "chatty":
            body = "\n".join(f'<s id="{i}">XX {t.strip()}</s>' for i, t in ids)
            return f"Sure! Here is the translation:\n{body}\nLet me know if you need changes."
        elif self.behaviour == "thinking":
            body = "\n".join(f'<s id="{i}">XX {t.strip()}</s>' for i, t in ids)
            return f"<think>let me translate these</think>\n{body}"

        return "\n".join(f'<s id="{i}">XX {t.strip()}</s>' for i, t in ids)


def _transcript(n=5):
    return Transcript(
        language="en",
        segments=[
            Segment(id=i, start=float(i), end=float(i) + 0.9, text=f"line {i}") for i in range(n)
        ],
        duration=float(n),
    )


def test_parse_extracts_ids_and_text():
    assert _parse('<s id="0">hola</s>\n<s id="1">adios</s>') == {0: "hola", 1: "adios"}


def test_parse_tolerates_unquoted_ids_and_newlines():
    assert _parse('<s id=3>multi\nline</s>') == {3: "multi\nline"}


async def test_timestamps_survive_translation():
    original = _transcript()
    result = await translate_transcript(original, "Spanish", client=FakeLLM())

    assert result.language == "Spanish"
    assert len(result.segments) == len(original.segments)
    for before, after in zip(original.segments, result.segments, strict=True):
        assert (after.id, after.start, after.end) == (before.id, before.start, before.end)
        assert after.text == f"XX {before.text}"


async def test_original_transcript_is_not_mutated():
    original = _transcript()
    await translate_transcript(original, "Spanish", client=FakeLLM())
    assert original.segments[0].text == "line 0"
    assert original.language == "en"


async def test_batching_splits_the_work():
    llm = FakeLLM()
    config = TranslationConfig(batch_size=2)
    result = await translate_transcript(_transcript(5), "Spanish", client=llm, config=config)

    assert llm.batch_sizes == [2, 2, 1]
    assert len(result.segments) == 5


async def test_dropped_segment_falls_back_to_a_single_call():
    llm = FakeLLM("drops_one")
    result = await translate_transcript(
        _transcript(3), "Spanish", client=llm, config=TranslationConfig(batch_size=3)
    )
    # Batch call plus one recovery call for the dropped segment.
    assert llm.calls == 2
    assert result.segments[-1].text == "SINGLE"
    assert len(result.segments) == 3


async def test_reordered_response_still_maps_by_id():
    result = await translate_transcript(
        _transcript(4), "Spanish", client=FakeLLM("reordered"),
        config=TranslationConfig(batch_size=4),
    )
    assert [s.text for s in result.segments] == [f"XX line {i}" for i in range(4)]


async def test_preamble_around_the_markers_is_ignored():
    result = await translate_transcript(_transcript(3), "Spanish", client=FakeLLM("chatty"))
    assert [s.text for s in result.segments] == [f"XX line {i}" for i in range(3)]


async def test_reasoning_blocks_are_stripped():
    result = await translate_transcript(_transcript(2), "Spanish", client=FakeLLM("thinking"))
    assert all("<think>" not in s.text for s in result.segments)
    assert result.segments[0].text == "XX line 0"


async def test_empty_transcript_short_circuits():
    llm = FakeLLM()
    result = await translate_transcript(
        Transcript(language="en", segments=[], duration=0.0), "Spanish", client=llm
    )
    assert result.segments == []
    assert llm.calls == 0


async def test_translated_transcript_exports_as_subtitles():
    result = await translate_transcript(_transcript(2), "Spanish", client=FakeLLM())
    srt = result.to_srt()
    assert "00:00:00,000 --> 00:00:00,900" in srt
    assert "XX line 0" in srt
