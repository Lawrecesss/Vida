# Arm comparison harness

Answers one question: **can frames + audio replace video input for visual analysis?**

If it can, the video path in `vida/analyze/` becomes dead weight — and dropping it
removes the transcode step, removes the `max_segment_mb` cap that forces 60-second
clips, and opens the model pool from "accepts video" to "accepts images".

This lives outside `vida/` on purpose. It is a measurement tool, not pipeline logic,
and the sdist `only-include` in `pyproject.toml` keeps it out of the distribution.

## The arms

| Arm | Content sent per window | Model requirement | ASR dependency |
|---|---|---|---|
| `video` | one transcoded clip, video + audio | accepts video input | none |
| `frames_text` | N stills + transcript excerpt as text | accepts images | **waits for ASR** |
| `frames_audio` | N stills + raw audio slice | accepts images + audio | none |

`frames_text` is the one to watch sceptically. It needs the transcript, which means
analysis can no longer run concurrently with transcription — `Vida.process()`
currently passes `transcript=None` precisely so the two stages overlap. Adopting it
would trade away that concurrency. `frames_audio` keeps the stages independent,
which is why it is worth measuring separately rather than assuming frames are frames.

All three share one skeleton in `arms.py` and differ only in the content builder.
No arm falls back across modes — a failed window is recorded as failed, because
failure rate per representation is one of the things being measured.

## Running it

```bash
# 1. Produce descriptions. Cached per (video, arm, frame count).
.venv/bin/python -m evals.run run --videos vids/ --out evals/results

# 2. Grade what survived into those descriptions.
cp evals/questions.example.json evals/questions.json   # then fill in real answers
.venv/bin/python -m evals.run score --out evals/results --questions evals/questions.json

# 3. Table.
.venv/bin/python -m evals.run report --out evals/results
```

Useful flags on `run`:

- `--arms video,frames_audio` — subset of arms
- `--frames 6,12,30` — sweep sampling density, the main lever for frames
- `--window 60` / `--overlap 2` — window planning, identical across arms
- `--model` / `--synthesis-model` — override the models from `VidaConfig`
- `--audio-format mp3|wav|flac|ogg` — `frames_audio` payload format
- `--force` — re-run cached arms
- `--keep-scratch` — keep clips and frames on disk to eyeball what was sent

`run` and `score` are separate so that re-grading with a different judge or a fixed
question set costs nothing and re-runs no video work.

## How scoring works

Each arm runs **once per video with no query**, producing a description. The judge
then answers the question set *from that description alone* — it never sees the
video, so it cannot credit information the arm failed to capture.

This measures what the representation preserved, and keeps the run at
`videos × arms × frame_counts` instead of multiplying by the question count.

Scores are 0 / 1 / 2 per question: absent, vague, clearly present.

## Writing questions

Put real answers in `questions.json` — the harness ships an example with
`REPLACE ME` placeholders, and grading against those is meaningless.

Two kinds, and the split is the entire point:

- **`descriptive`** — setting, people, objects, on-screen text. Frames should hold
  their own here.
- **`temporal`** — ordering, direction, speed, what changed between start and end.
  This is where frames are expected to lose, and where sampling density should show
  up as a visible gradient across `--frames 6,12,30`.

The report never pools them. A combined number would average away the exact
distinction the comparison exists to find.

## Reading the result

The decision is not "which arm wins overall". It is:

1. Does `frames_*` match `video` on **descriptive**? If yes, the video path buys you
   nothing for the common case.
2. How large is the **temporal** gap, and does more frames close it? If 30 frames per
   window closes it, density is the fix and video is still redundant. If it does not,
   video earns its place for motion-heavy input.
3. What does each cost? `report` totals requests, uploaded bytes, and wall-clock —
   `video` uploads roughly 6 MB of base64 per 60-second window, and frames at low
   detail are typically an order of magnitude less.

Two sample videos will not settle this. A dozen spanning talking-head,
screen-recording, and action is the minimum worth concluding from.
