# Transcription accuracy harness

Answers one question the rest of the repo cannot: **did that change actually
improve the words?**

Everything in `evals/` above this directory is LLM-judged *visual analysis*
quality. It is structurally the wrong shape for transcription — there is a
correct answer here, and it is a string. So this is a sibling module, not an
extra arm: fixtures pair media with a hand-corrected reference, and scoring is
`jiwer` word- and character-error rate rather than a judge model.

Without this, every accuracy change is a guess. With it, each one is a number
against the same fixtures before and after.

## Install

```bash
uv pip install -e '.[eval]'     # adds jiwer
```

## Running it

```bash
# 1. Transcribe. Cached per (fixture, config) — re-runs cost nothing.
python -m evals.asr.run run --configs groq:whisper-large-v3,local:small,local:medium

# 2. Score the cached hypotheses. Free and offline.
python -m evals.asr.run score

# 3. Table.
python -m evals.asr.run report
```

`run` and `score` are separate so that revising the normalisation in `score.py`
re-runs no ASR.

Flags on `run`, each of which becomes part of the cached config label so an
A/B lands in two files rather than overwriting one:

- `--glossary` — pass each fixture's glossary terms to the backend (stream 3)
- `--dialogue-filter 'pan=mono|c0=FC'` — dialogue isolation before the downmix (stream 4)
- `--silence-aware` — snap chunk boundaries to silence (stream 5)
- `--no-audio-filter` — baseline with the denoise chain off
- `--chunk-seconds` / `--prompt` / `--force`

## Fixtures

`fixtures/manifest.json` (start from `manifest.example.json`) lists clips and
their references. **The clips are gitignored and the references are not** —
movie footage is copyrighted, the transcripts are ours. A fixture whose media
is missing is skipped with a note, so a fresh clone still runs.

Building the ground truth, given that no labeled data exists today:

1. Pick 4–5 clips of 60–120s: quiet dialogue, dialogue under a music bed, a
   noisy action scene, accented speech, and one rich in character names — the
   last doubles as the glossary fixture.
2. Transcribe once with the best config you have: `vida transcribe clip.mp4 -o clip.srt`.
3. Hand-correct that `.srt` against the clip and save it as
   `fixtures/<id>.reference.srt`. Timestamps do not need to be frame-accurate;
   WER scores joined text and the harness throws the timecodes away.
4. Record a baseline **before** changing anything, then re-run after each change.

Don't reuse `vids/test2.mp4` from `tests/_samples.py`. That is a generic
action-camera clip for pipeline unit tests, and mixing it in conflates CI
fixtures with accuracy fixtures.

## Reading the result

Read the **deleted** column before the WER. Whisper's failure under a music bed
is not mistranscription, it is silence — lines that simply never come back — and
a WER made of deletions has a different fix from one made of substitutions.

Per-clip-type WER is reported separately for the same reason the visual harness
never pools descriptive and temporal scores: a quiet clip and a music-heavy one
average into a number describing neither.

A change earns its default only when it moves these numbers on real fixtures.
Every knob the accuracy work added ships **off**.
