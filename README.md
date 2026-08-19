# Vida

A Python SDK for getting text out of video, fast: **analyze** what a video shows,
**transcribe** what is said in it, and **translate** that into any language —
with timestamps intact, so the output drops straight into a subtitle track.

```python
import asyncio
from vida import Vida

async def main():
    async with Vida() as vida:
        transcript = await vida.transcribe("talk.mp4")
        spanish = await vida.translate(transcript, "Spanish")
        spanish.save("talk.es.srt")

asyncio.run(main())
```

## Why it's quick

The slow part of this problem is long media, and long media is embarrassingly
parallel. VidA leans on that:

- **Audio, not video, goes to the ASR model.** A one-hour video becomes ~30 MB
  of 16 kHz mono FLAC instead of gigabytes of H.264.
- **Chunks fan out.** Long audio is split into overlapping chunks transcribed
  concurrently, then stitched back onto one timeline — so wall-clock time tracks
  the *longest* chunk, not the sum.
- **Translation batches and fans out too.** Segments go out in numbered batches
  in parallel; N target languages cost about as much as the slowest one.
- **Transcription and analysis overlap.** `process()` runs both at once.

## Install

```bash
pip install 'vida[groq]'      # fastest hosted transcription
pip install 'vida[openai]'    # OpenAI Whisper
pip install 'vida[local]'     # faster-whisper, fully offline
pip install 'vida[all]'       # everything, including the chat agent
```

You also need **ffmpeg**. A system install is used when present; otherwise VidA
falls back to the binary bundled with `imageio-ffmpeg`, which is a core
dependency — so it works out of the box either way.

## Configure

```bash
export GROQ_API_KEY=...         # transcription (recommended)
export OPENROUTER_API_KEY=...   # translation and visual analysis
```

Either a `.env` or a `.env.secret` file in the working directory is loaded
automatically.

Check what's usable right now:

```bash
vida backends
```

## Usage

### Transcribe

```python
transcript = await vida.transcribe("talk.mp4", language="en")

transcript.text                # the whole thing as one string
transcript.segments[0].start   # 0.0
transcript.to_srt()            # subtitle text
transcript.save("talk.srt")    # format inferred from the extension
```

`language` is a hint — omit it to auto-detect. `prompt=` biases decoding toward
names and jargon the model would otherwise mangle.

### Translate

Timestamps and segment ids survive, so a translated transcript is still a valid
subtitle track:

```python
japanese = await vida.translate(transcript, "Japanese")
japanese.save("talk.ja.vtt")

# Several languages at once — these run concurrently
everything = await vida.translate_all(transcript, ["Spanish", "French", "Japanese"])
```

`translate()` also takes a plain string and returns a plain string.

### Analyze

This one *watches* the video rather than listening to it:

```python
analysis = await vida.analyze("talk.mp4", query="What product is being demoed?")
print(analysis.summary)
```

Passing `transcript=` grounds the visual descriptions in what is actually being
said, which noticeably sharpens them.

### Everything at once

```python
insight = await vida.process(
    "talk.mp4",
    transcribe=True,
    translate_to=["Spanish", "Japanese"],
    analyze=True,
)

insight.transcript.text
insight.translations["Spanish"].to_srt()
insight.analysis.summary
insight.timings                    # {'transcribe': 4.1, 'analyze': 22.7, ...}
```

### Straight to subtitle files

```python
paths = await vida.subtitles("talk.mp4", languages=["Spanish", "Japanese"], fmt="srt")
# {'en': 'talk.en.srt', 'Spanish': 'talk.spanish.srt', ...}
```

### Synchronous code

Every method has a blocking twin:

```python
from vida import Vida

transcript = Vida().transcribe_sync("talk.mp4")
```

They raise if called from inside a running event loop — await the async method
there instead.

## CLI

```bash
vida transcribe talk.mp4 -o talk.srt
vida translate  talk.mp4 --to Spanish --to Japanese
vida analyze    talk.mp4 -q "what is being demonstrated?"
vida info       talk.mp4
vida backends
```

## Choosing an ASR backend

| Backend  | Speed | Cost | Notes |
|----------|-------|------|-------|
| `groq`   | fastest | cheap | `whisper-large-v3-turbo`; needs `GROQ_API_KEY` |
| `openai` | fast | moderate | `whisper-1`; 25 MB per request, handled by chunking |
| `local`  | slowest on CPU | free | `faster-whisper`; fully offline, downloads weights on first run |

`Vida()` defaults to `auto`, which picks the fastest backend whose key is
present. Force one explicitly:

```python
vida = Vida(asr_backend="local", asr_model="medium")
```

## Configuration

Anything can be tuned through `VidaConfig`, or the matching environment variable:

```python
from vida import Vida, VidaConfig, ASRConfig

config = VidaConfig(
    asr=ASRConfig(backend="groq", chunk_seconds=300, concurrency=16),
)
vida = Vida(config)
```

| Variable | Default | Meaning |
|---|---|---|
| `VIDA_ASR_CHUNK_SECONDS` | `600` | Audio longer than this is split |
| `VIDA_ASR_CONCURRENCY` | `8` | Chunks transcribed at once |
| `VIDA_TRANSLATION_BATCH_SIZE` | `40` | Segments per translation call |
| `VIDA_TRANSLATION_CONCURRENCY` | `8` | Translation batches in flight |
| `VIDA_ANALYSIS_CONCURRENCY` | `5` | Video clips analyzed at once |
| `VIDA_WORK_DIR` | temp dir | Where scratch files go |

## Errors

Everything derives from `VidaError`:

```python
from vida import VidaError, ConfigurationError, MediaError

try:
    await vida.transcribe("talk.mp4")
except ConfigurationError as exc:
    ...   # missing key or unavailable backend — the message says which
except MediaError as exc:
    ...   # unreadable file, or no audio track
except VidaError as exc:
    ...
```

## Optional agent layer

For natural-language use, `pip install 'vida[agent]'` adds a LangGraph ReAct
agent over the same tools. It is not imported by the core SDK, so it costs
nothing if unused:

```python
from vida.agent import VidaAgent

async with VidaAgent() as agent:
    print(await agent.run("What's said in demo.mp4, and give me the Spanish?"))
```

## The demo app

`backend/` is a FastAPI service that wraps the SDK, and `frontend/` is a Next.js
UI for it.

```bash
pip install -r backend/requirements.txt
cd backend && python run.py            # http://localhost:8000

cd frontend && npm install && npm run dev
```

Endpoints: `/upload`, `/transcribe`, `/translate`, `/analyze`, `/process`,
`/process/stream`, `/subtitles`, `/chat`, `/backends`.

## Development

```bash
pip install -e '.[dev]'
pytest
```

## License

MIT
