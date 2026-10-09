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
pip install vida-sdk              # hosted transcription, translation, analysis
pip install 'vida-sdk[openai]'    # also: talk to OpenAI Whisper directly
pip install 'vida-sdk[local]'     # also: faster-whisper, fully offline
pip install 'vida-sdk[all]'       # everything, including the chat agent
```

The base install is all you need. Every hosted stage — transcription included —
goes to OpenRouter over plain HTTP, so there is no vendor SDK to add and no
extra to remember; the extras above are only for the alternative ASR backends.

The distribution is `vida-sdk`; the import name is just `vida`.

On Debian and Ubuntu, `pip install` into the system Python is blocked by PEP
668. Use `uv tool install vida-sdk` (or `pipx`) for the CLI, or install into a
virtual environment.

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
export OPENROUTER_API_KEY=...   # transcription, translation, visual analysis
```

One key for all three stages, and one bill. `OPENAI_API_KEY` is needed only for
the `openai` ASR backend; the `local` one needs no key at all.

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

| Backend      | Speed | Cost | Notes |
|--------------|-------|------|-------|
| `openrouter` | fastest | cheap | default; `openai/whisper-large-v3`, needs only `OPENROUTER_API_KEY` |
| `openai`     | fast | moderate | `whisper-1` straight from OpenAI; 25 MB per request, handled by chunking |
| `local`      | slowest on CPU | free | `faster-whisper`; fully offline, downloads weights on first run |

`Vida()` defaults to `auto`, which takes the first configured backend, preferring
`openrouter` — the one key the rest of the SDK already needs. Force one
explicitly:

```python
vida = Vida(asr_backend="local", asr_model="medium")
```

### Choosing a model per call

No stage is pinned to a model. Each takes a `model` argument that overrides the
configured one for that call only, and the id is passed to the provider
untouched — so a model published after this release works without an upgrade:

```python
async with Vida() as vida:                       # one client, pooled connections
    fast  = await vida.transcribe("a.mp4", model="openai/whisper-large-v3-turbo")
    exact = await vida.transcribe("b.mp4", model="openai/whisper-large-v3")
    ja    = await vida.translate(exact, "Japanese", model="qwen/qwen3-max")
```

`process()` and `subtitles()` take the same thing per stage — `asr_model`,
`translation_model`, `analysis_model`, `synthesis_model`. This is the layer a
server works at: hold one `Vida` for the process and let each request name its
own models, rather than keeping a client per model or restarting to change one.
The demo backend does exactly that — every endpoint accepts these as optional
body fields and falls back to the server's defaults when they are absent.

Two things differ between STT models, and Vida absorbs both rather than making
you check first:

- **Segment timestamps are not universal.** The Whisper models return them; the
  newer token-priced models (`openai/gpt-4o-transcribe`) reject the request
  outright. Vida asks for them, and on refusal retries for flat text and returns
  a single cue spanning the audio — a poor subtitle track, but a transcript. The
  answer is remembered per model id, so only the first chunk of a file pays for
  finding out.
- **Input size limits are per model.** A model may refuse a payload the Whisper
  models accept. Lower `VIDA_ASR_CHUNK_SECONDS`; the pipeline already splits long
  audio, so a smaller chunk is the whole fix.

Nothing validates a model id against an allowlist — a wrong one surfaces as the
provider's own error. Be aware OpenRouter reports whichever constraint it checks
first, so a nonexistent id does not reliably say "does not exist".

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

**Or let it measure the source.** That chain is fixed, and `afftdn=nf=-30`
inside it asserts where the noise floor sits. A constant cannot be right for
both a studio take and a windy one — mixing wind-like noise into one 120 s
address at three levels put the real floor anywhere from -54 dB to -29 dB while
the speech level barely moved:

| | noise floor | speech | margin |
|---|---|---|---|
| clean | -53.9 dB | -29.0 dB | 24.9 dB |
| + light noise | -48.8 dB | -28.9 dB | 19.9 dB |
| + moderate noise | -38.3 dB | -28.5 dB | 9.8 dB |
| + heavy noise | -28.7 dB | -25.7 dB | 2.9 dB |

`VIDA_ASR_ADAPTIVE_DENOISE=true` measures that margin in one bounded ffmpeg
pass over the source and builds the chain to match: no spectral denoising above
20 dB, where it can only trade speech for artefacts; harder denoising below
10 dB; and the floor it measured rather than the constant. Band-limiting and
loudness normalisation always run.

It is **off by default and not yet recommended**, because the measurement that
would justify turning it on does not exist. A/B/C over those same clips put it
ahead of the fixed chain in every condition and behind *unfiltered* audio on
the heavy one, all by a handful of words out of 233 — differences smaller than
the run-to-run spread of the hosted model on an identical request. Settle it
with `evals/asr` on real fixtures before trusting it:

```bash
python -m evals.asr.run run --configs openrouter:openai/whisper-large-v3 --adaptive-denoise
```

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

On the `openrouter` backend that prompt is a *provider* option rather than a
request field — there is no provider-neutral spelling for it, so Vida sends it
under the slugs documented to accept one. A provider that does not take a prompt
ignores it silently, which is the one case where a glossary can have no effect;
`VIDA_ASR_PROVIDER_OPTIONS` lets you name another slug to carry it.

### Longer-form and film-like material

Three further knobs exist for it. All three default to off, because none of them
has been measured to help on general material — see `evals/asr/` for the harness
that would settle it:

| Knob | What it does |
|---|---|
| `VIDA_ASR_MODEL=medium` (or `large-v3`) | On `local`, the default is `small`, picked for interactive latency. Batch work should trade that back for accuracy. On `openrouter` the equivalent is `openai/whisper-large-v3` over `...-turbo`. |
| `VIDA_ASR_DIALOGUE_FILTER='pan=mono\|c0=FC'` | Keeps only the 5.1 centre channel, where film dialogue is mixed, discarding the score and effects bed. Needs a genuine 5.1 source; `pan=mono\|c0=0.5*c0+0.5*c1` is the weaker stereo equivalent. |
| `VIDA_ASR_SILENCE_AWARE_CHUNKING=1` | Moves chunk boundaries into gaps between lines rather than cutting on the clock. |

### Measuring any of this

`evals/asr/` scores word- and character-error rate against hand-corrected
references, so a change can be shown to help rather than assumed to:

```bash
uv pip install -e '.[eval]'
python -m evals.asr.run run --configs openrouter:openai/whisper-large-v3,local:medium
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
    asr=ASRConfig(backend="openrouter", chunk_seconds=300, concurrency=16),
)
vida = Vida(config)
```

| Variable | Default | Meaning |
|---|---|---|
| `VIDA_ASR_MODEL` | backend default | Process-wide ASR model; a per-call `model=` overrides it |
| `VIDA_ASR_PROVIDER_OPTIONS` | none | JSON object of per-provider transcription options, keyed by OpenRouter provider slug |
| `VIDA_ASR_AUDIO_FILTER` | denoise chain | ffmpeg filter applied during extraction; empty disables |
| `VIDA_ASR_GLOSSARY` | none | Comma-separated terms to bias decoding toward |
| `VIDA_ASR_ADAPTIVE_DENOISE` | `false` | Build the denoise chain from the source's measured noise floor instead of using the fixed one |
| `VIDA_ASR_NOISE_SAMPLE_SECONDS` | `120` | Seconds of source the measurement above listens to |
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
UI for it. They are separate services with separate images — the SDK is not one
of them, it is a library compiled into the backend.

```bash
make up      # both services, http://localhost:3000 and :8000
make dev     # same, with hot reload on both
make down
```

Keys are read from `.env` or `.env.secret` at the repo root; both are optional,
and the stack starts without them (`/backends` will just report nothing ready).
Uploaded media lives on a named volume, so it survives a restart — `make clean`
is what deletes it.

Or run them directly, without Docker:

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
