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
parallel. Vida leans on that:

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
pip install 'vida-sdk[groq]'      # fastest hosted transcription
pip install 'vida-sdk[openai]'    # OpenAI Whisper
pip install 'vida-sdk[local]'     # faster-whisper, fully offline
pip install 'vida-sdk[all]'       # everything, including the chat agent
```

The distribution is `vida-sdk`; the import name is just `vida`.

On Debian and Ubuntu, `pip install` into the system Python is blocked by PEP
668. Use `uv tool install 'vida-sdk[groq]'` (or `pipx`) for the CLI, or install
into a virtual environment.

### Running the local backend on a GPU

The `local` backend picks the GPU when CUDA works and falls back to the CPU when
it does not, so nothing is required to get started. To make the GPU path work on
an NVIDIA card, add the CUDA 12 runtime:

```bash
pip install 'vida-sdk[local,cuda]'
```

That pulls ~1.4 GB of NVIDIA wheels, which is why it is a separate extra and not
part of `local` or `all`. No `LD_LIBRARY_PATH` setup is needed — the libraries
are loaded from site-packages directly. Force a device with
`VIDA_LOCAL_DEVICE=cuda|cpu` if you would rather not rely on the probe.

You also need **ffmpeg**. A system install is used when present; otherwise Vida
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
| `groq`   | fastest | cheap | `whisper-large-v3`; needs `GROQ_API_KEY` |
| `openai` | fast | moderate | `whisper-1`; 25 MB per request, handled by chunking |
| `local`  | slowest on CPU | free | `faster-whisper`; fully offline, downloads weights on first run |

`Vida()` defaults to `auto`, which picks the fastest backend whose key is
present. Force one explicitly:

```python
vida = Vida(asr_backend="local", asr_model="medium")
```

### Getting the words right

Two things decide how much of a noisy recording you actually get back.

**Clean the audio first.** Whisper does not merely mistranscribe through wind
and traffic — it goes quiet, returning nothing at all for stretches where
someone is clearly talking. Vida runs an ffmpeg denoise chain during the one
decode it has to do anyway. On a wind-heavy action-camera clip that was worth
25% more segments and a third more words:

| | segments | speech covered | words |
|---|---|---|---|
| `VIDA_ASR_AUDIO_FILTER=""` | 26 | 70s | 122 |
| default chain | 32–38 | 92–113s | 152–168 |

It also restores the confidence scores the silence filter depends on, which
noise otherwise pushes into the range where real speech and hallucinations are
indistinguishable. Set `VIDA_ASR_AUDIO_FILTER=""` for clean studio audio, where
the filtering only costs CPU.

**Pin the language.** Whisper decides on a language for every 30-second window,
and on accented speech it changes its mind mid-file: half a recording comes
back in English and the rest in a language that merely sounds like it, invented
word for word. Vida detects once from the opening `VIDA_ASR_DETECT_SECONDS` and
pins that answer for every window.

That detection is a guess, and on hard audio it is the weakest link in the
pipeline — the same recording has been called English, Malay, and Burmese
depending on which 30 seconds the detector was shown. **Pass `language=`
whenever you know it.** That path is exact:

```python
transcript = await vida.transcribe("talk.mp4", language="en")
```

A genuinely multilingual recording is the one case that wants the opposite —
set `VIDA_ASR_DETECT_SECONDS=0` to let each window decide for itself.

**Name the vocabulary it cannot guess.** Whisper renders an unfamiliar proper
noun as whatever ordinary words it sounds like, consistently and confidently, so
a character name wrong once is wrong every time it is said. Pass the names:

```python
transcript = await vida.transcribe(
    "film.mp4",
    language="en",
    glossary=["Aelith", "Corvain", "the Sundering"],
)
```

Or `vida transcribe film.mp4 --glossary Aelith --glossary Corvain`, or
`VIDA_ASR_GLOSSARY` for terms that apply to everything. Whisper's only
vocabulary mechanism is the free-text prompt, so the terms are folded into it
for you, with the glossary given priority over `prompt=` when the model's
~224-token prompt window binds.

### Longer-form and film-like material

Three further knobs exist for it. All three default to off, because none of them
has been measured to help on general material — see `evals/asr/` for the harness
that would settle it:

| Knob | What it does |
|---|---|
| `VIDA_ASR_MODEL=medium` (or `large-v3`) | On `local`, the default is `small`, picked for interactive latency. Batch work should trade that back for accuracy. |
| `VIDA_ASR_DIALOGUE_FILTER='pan=mono\|c0=FC'` | Keeps only the 5.1 centre channel, where film dialogue is mixed, discarding the score and effects bed. Needs a genuine 5.1 source; `pan=mono\|c0=0.5*c0+0.5*c1` is the weaker stereo equivalent. |
| `VIDA_ASR_SILENCE_AWARE_CHUNKING=1` | Moves chunk boundaries into gaps between lines rather than cutting on the clock. |

### Measuring any of this

`evals/asr/` scores word- and character-error rate against hand-corrected
references, so a change can be shown to help rather than assumed to:

```bash
uv pip install -e '.[eval]'
python -m evals.asr.run run --configs groq:whisper-large-v3,local:medium
python -m evals.asr.run score
python -m evals.asr.run report
```

Read the deleted-words column before the WER. Whisper's failure under a music
bed is not mistranscription but silence, and the two have different fixes.

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
| `VIDA_ASR_MODEL` | backend default | Override the ASR model without touching code |
| `VIDA_ASR_AUDIO_FILTER` | denoise chain | ffmpeg filter applied during extraction; empty disables |
| `VIDA_ASR_GLOSSARY` | none | Comma-separated terms to bias decoding toward |
| `VIDA_ASR_DIALOGUE_FILTER` | none | ffmpeg filter run in the source channel layout, before the downmix |
| `VIDA_ASR_DETECT_SECONDS` | `30` | Audio sampled to pin the language up front; `0` disables |
| `VIDA_ASR_CHUNK_SECONDS` | `600` | Audio longer than this is split |
| `VIDA_ASR_SILENCE_AWARE_CHUNKING` | `false` | Snap chunk boundaries to gaps in the speech |
| `VIDA_ASR_CHUNK_BOUNDARY_SEARCH` | `3` | How far either side of a boundary to look for silence |
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

For natural-language use, `pip install 'vida-sdk[agent]'` adds a LangGraph ReAct
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
uv venv && uv pip install -r backend/requirements.txt
cd backend && uv run python run.py     # http://localhost:8000

cd frontend && npm install && npm run dev
```

Endpoints: `/upload`, `/transcribe`, `/translate`, `/analyze`, `/process`,
`/process/stream`, `/subtitles`, `/chat`, `/backends`.

## Development

```bash
uv venv
uv pip install -e '.[dev]'
uv run pytest
```

## License

MIT
