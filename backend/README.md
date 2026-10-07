# Vida demo backend

A thin FastAPI service over the `vida` SDK. It exists to give the `frontend/`
UI (and anything else) an HTTP surface for transcription, translation, and
visual analysis — the actual pipeline logic all lives in `../vida`; nothing
here talks to ffmpeg or a model provider directly.

## Run it

```bash
make up      # from the repo root: this service plus the frontend
```

Or natively:

```bash
uv venv
uv pip install -r requirements.txt   # installs vida-sdk editable from ../
uv run python run.py                 # http://localhost:8000
```

`requirements.txt` installs the SDK with `-e ../[agent]`, so backend
changes and SDK changes stay in sync without a reinstall. `run.py` also adds
`../vida` to uvicorn's reload watch list — the default only watches the
working directory, which would otherwise leave SDK edits invisible until a
manual restart.

Needs the same environment as the SDK (`OPENROUTER_API_KEY`, ...) — see the
root `.env.example`. A `.env` or `.env.secret` found upward
from the working directory is loaded automatically.

## In Docker

`Dockerfile` builds from the **repo root**, not from here: `requirements.txt`
installs the SDK with `-e ../`, so `vida/` and `pyproject.toml` have to be in
the build context. `docker build backend/` cannot work; `compose.yaml` at the
root sets `context: .` for this reason.

The image installs a system **ffmpeg**, which also gets you `ffprobe` — the
`imageio-ffmpeg` fallback the SDK carries ships no ffprobe, which would push
every probe onto the slower `ffmpeg -i` stderr parse in `vida/media/ffmpeg.py`.

It runs **one uvicorn worker on purpose.** `api/deps.py` and `api/agent_state.py`
both hold process-wide singletons — the pooled `Vida` client and the LangGraph
agent — so a second worker means a second pool and a second agent rather than
more throughput. Scaling this service out needs that state moved first.

Uploads go to `/data/uploads` on a named volume rather than the default
`/tmp/vida_uploads`: a client calls `/upload`, then hands the returned path back
to `/process`, so the file has to outlive anything that happens between the two.

## Architecture

`api/deps.py` holds one process-wide `Vida` client (`get_vida()`), so HTTP
connections pool across requests instead of being rebuilt per call. It is
closed in `api/app.py`'s lifespan handler on shutdown.

`api/router.py` is the whole surface: request/response models as Pydantic,
handlers that call the SDK, done. Nothing above it re-implements pipeline
logic — if a change looks like it belongs in `vida/`, it does.

Model ids come in the request body, not from this service's environment. Every
operation takes optional `asr_model`, `translation_model`, `analysis_model` and
`synthesis_model` fields and hands them to the SDK, which passes them to the
provider untouched; omitting one falls back to the server's configured default.
That is why one shared `Vida` is enough for clients that want different models:
the choice is per call, so nothing here is pinned to a model and no redeploy is
needed to offer one that shipped yesterday. `GET /backends` reports the defaults
in force, which is the one thing a client cannot derive from an id it chose
itself. Nothing validates these strings against an allowlist — an unknown model
surfaces as the provider's own 404 through the usual `502`.

Client-supplied `video_path` values are never trusted directly. Every request
that carries one is routed through `resolve_upload()`, which resolves the
path and checks it against `UPLOAD_DIR` — that's what stops a request from
naming an arbitrary file on the host.

`/process/stream` and `/chat/stream` are Server-Sent Events. Errors during a
stream are emitted as SSE `error` events rather than raised as HTTP errors,
since the response has already started — the frontend treats a stream error
event as a failed run, not a crash.

## Endpoints

All under `/api/v1`, plus `/health` at the root.

| Method | Path | What it does |
|---|---|---|
| `POST` | `/upload` | Stream a video/audio file to disk, probe it, return a handle (`video_path`) for the other endpoints |
| `DELETE` | `/upload` | Remove a previously uploaded file |
| `POST` | `/transcribe` | Transcribe one video |
| `POST` | `/translate` | Transcribe, then translate into one or more target languages |
| `POST` | `/analyze` | Visual analysis of a video, optionally focused by a query |
| `POST` | `/process` | Transcribe + translate + analyze in one call |
| `POST` | `/process/stream` | Same as `/process`, as Server-Sent Events — a stage event per pipeline step |
| `POST` | `/subtitles` | Straight to `.srt`/`.vtt` text |
| `POST` | `/chat` | One-shot message to the optional LangGraph agent |
| `POST` | `/chat/stream` | Same, streamed |
| `GET` | `/backends` | Which ASR backends are usable (i.e. which keys are set), the default model each resolves to, and the LLM defaults in force |

Upload is capped at `VIDA_MAX_UPLOAD_MB` (default 1024) and written to disk in
chunks — a whole video is never buffered in memory.

## Configuration

Backend-specific env vars, on top of everything the SDK reads:

| Variable | Default | Meaning |
|---|---|---|
| `VIDA_CORS_ORIGINS` | `http://localhost:3000` | Comma-separated allowed origins. Never defaults to `*` — that would let any site call this API from a user's browser. |
| `VIDA_UPLOAD_DIR` | `/tmp/vida_uploads` | Where uploaded media is written and served from |
| `VIDA_MAX_UPLOAD_MB` | `1024` | Per-file upload cap |

## Notes for changes here

- Keep pipeline logic in `vida/`. This layer's job is request handling,
  upload safety, and shaping SDK results into HTTP responses — not decoding
  media or calling a model.
- Every new endpoint that takes a `video_path` from the client must go through
  `resolve_upload()`.
- SSE endpoints emit errors as stream events, not HTTP error codes — match
  that pattern rather than raising once the stream has started.
