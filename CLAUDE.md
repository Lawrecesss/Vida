# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Three things in one tree:

- `vida/` — the published SDK (distribution `vida-sdk`, import name `vida`). This is the product; everything else is downstream of it.
- `backend/` + `frontend/` — a demo FastAPI service and Next.js UI over the SDK. Excluded from the sdist.
- `evals/` — two measurement harnesses, both excluded from the sdist. `evals/` proper compares video vs. frames representations for visual analysis (LLM-judged, `evals/README.md`); `evals/asr/` scores transcription word-error rate against hand-corrected references (`jiwer`, `evals/asr/README.md`). They are separate modules because one has a correct answer and the other does not.

## Commands

```bash
uv venv
uv pip install -e '.[dev]'      # dev extras: pytest, pytest-asyncio, ruff

uv run pytest                   # full suite (offline — every network call is stubbed)
uv run pytest tests/test_pipeline.py::test_name -q
uv run ruff check .             # what CI lints with
```

`asyncio_mode = "auto"` is set, so `async def test_*` needs no marker.

Tests that need real media (`vids/`, Git LFS) skip themselves unless `git lfs pull` has been run — `tests/_samples.py` checks file *content*, not existence, because an unfetched LFS pointer is still a file.

`tests/test_live_smoke.py` hits the real OpenRouter API and is skipped unless `VIDA_LIVE_SMOKE=1`. It exists because everything else is stubbed, so a withdrawn model slug is otherwise invisible — 0.1.0 shipped with translation broken that way. Run it after changing any default model id.

Accuracy work is measured, not guessed at:

```bash
uv pip install -e '.[eval]'                  # adds jiwer
python -m evals.asr.run run --configs groq:whisper-large-v3,local:medium
python -m evals.asr.run score && python -m evals.asr.run report
```

Fixture media is gitignored (copyrighted clips); the `.reference.srt` files are committed. A fixture whose media is absent is skipped, so this runs on a fresh clone and reports nothing.

Demo app:

```bash
uv pip install -r backend/requirements.txt   # installs the SDK editable from ../
cd backend && uv run python run.py           # :8000, reloads on ../vida changes too
cd frontend && npm install && npm run dev    # :3000
cd frontend && npm run lint
```

Release is tag-driven (`v*` → `.github/workflows/publish.yml`): lint + test on 3.10–3.12, then the live smoke gate, then PyPI trusted publishing. The tag must match `version` in `pyproject.toml` or the build job fails.

## Architecture

`Vida` (`vida/client.py`) is the only public entry point. It holds a `VidaConfig`, lazily builds two collaborators — a `Transcriber` and an `OpenRouterClient` — and delegates. It owns scratch directories and HTTP lifetime; the stage modules own the logic and take everything they need as arguments.

Stage modules, all independent of each other:

- `vida/asr/` — backends (`groq`, `openai`, `local`) behind `Transcriber`, plus `pipeline.py`, which is where the real work is.
- `vida/translate/core.py` — batched, concurrent LLM translation.
- `vida/analyze/core.py` — clip-wise visual analysis, then a synthesis pass.
- `vida/media/` — all ffmpeg. Nothing above this layer shells out.
- `vida/export/subtitles.py` — SRT/VTT rendering.
- `vida/agent/` — optional LangGraph ReAct layer. **Never import it from the core SDK**; keeping LangGraph off the fast path is deliberate.

Everything crosses module boundaries as the pydantic models in `vida/types.py` (`Transcript`, `Segment`, `Analysis`, `VideoInsight`), which is why SDK results drop straight into FastAPI responses.

### The invariants worth knowing before editing

**Segment timestamps are global.** A `Transcriber` only ever sees one already-chunked audio file whose timeline starts at zero (`vida/asr/base.py`). Splitting, timestamp shifting, and de-overlapping at seams are `pipeline.merge_chunk_transcripts`' job. Do not push timeline awareness down into a backend.

**Segment ids survive translation.** `translate/core.py` sends segments as `<s id="N">…</s>` and reattaches results by id — that is the entire reason a translated transcript is still a valid subtitle track. Any change to the prompt or the parser must preserve the round trip, and any new default translation model must be verified to honour the markers (that's what the live smoke test checks).

**Transcription and analysis overlap on purpose.** `Vida.process()` passes `transcript=None` into `analyze_video` so the two stages run concurrently. Grounding analysis in the transcript improves it, but serializes the pipeline — that trade-off is the question `evals/` exists to answer. Don't "fix" it by awaiting the transcript first.

**Audio cleanup and language pinning are load-bearing, not cosmetic.** Whisper goes *silent* through noise rather than mistranscribing, and re-detects language per 30-second window, drifting mid-file on accented speech. So: an ffmpeg denoise chain runs during the one decode that has to happen anyway (`DEFAULT_AUDIO_FILTER`), and the language is detected once up front and pinned. The filter also restores the confidence scores `vida/asr/silence.py` needs to separate real speech from hallucinated "Thank you." — its thresholds are calibrated against measured cases documented in that module's docstring. Changing either changes the other.

Language detection runs against the *unprocessed* media (`probe_source`), not the denoised audio: the detector expects natural audio.

Filter order in `vida/media/audio.py:_filter_graph()` is load-bearing in the same way: `dialogue_filter` runs **before** the mono downmix because it reads the source channel layout, and `audio_filter` runs **after** because it was calibrated against 16 kHz mono. Swapping them silently changes what both were measured to do.

**A vocabulary prompt is assembled once, in the pipeline.** `transcribe_audio_file()` is the single choke point both the single- and multi-chunk paths funnel through, so `vida/asr/glossary.py:build_prompt()` is called there rather than per backend or per chunk. Every chunk gets the same prompt — each is an independent request with no memory of the last.

**Accuracy knobs ship off.** Glossary biasing, `dialogue_filter`, and `silence_aware_chunking` all default to unset/`False`, and the default-path behaviour is byte-identical to what it was before they existed — `_filter_graph()` is tested for exactly that. None of them becomes a default until `evals/asr` shows a WER delta on real fixtures. The reason is history: this pipeline's tuning is calibrated against measured cases, and a plausible-sounding audio change that nobody measured is how you silently regress the thing.

**Config is dataclasses with env-var defaults** (`vida/config.py`), loaded from `.env.secret` or `.env` found upward from the CWD. Every knob is settable three ways — constructor kwarg, config object, env var — and the README table plus `.env.example` are part of the contract; update both when adding one.

### Demo backend

`backend/api/deps.py` holds one process-wide `Vida` so connections pool across requests. Client-supplied `video_path` values are always run through `resolve_upload()`, which confines them to `UPLOAD_DIR` — do not read a request-supplied path directly. `/process/stream` and `/chat/stream` are SSE; errors are emitted as events rather than raised, so the stream reports instead of 500-ing.

The frontend targets `NEXT_PUBLIC_API_URL`, defaulting to `http://localhost:8000/api/v1`. CORS defaults to `http://localhost:3000`, never `*`.

### Frontend

Next.js 16 / React 19 with shadcn components in `frontend/components/ui/`. Per `frontend/AGENTS.md`: this Next.js version has breaking changes relative to older conventions — read the relevant guide in `node_modules/next/dist/docs/` before writing code against its APIs.

## Conventions

Ruff with `E,F,W,I,UP,B,SIM,ASYNC,RET` at line-length 100; formatter owns line length (`E501` off).

Comments here explain *why*, usually citing a measured failure — the wind-heavy clip, the withdrawn model slug, the LFS pointer on CI. Match that: a comment that restates the code doesn't belong, and a non-obvious threshold without its calibration does.

Every async public method has a `*_sync` twin that runs `asyncio.run` and closes the client afterward (clients are bound to their creating loop). They deliberately raise inside a running loop.
