# Vida

- `core/` — the library (`vida.transcribe`): ffmpeg extracts audio, OpenRouter transcribes it.
- `backend/` — FastAPI test harness for the library. `POST /generate` (multipart `video`, optional `model`) returns the transcript.
- `frontend/` — Next.js test UI: pick a video, press Generate, read the output in the side terminal.

```bash
cp .env.example .env    # set OPENROUTER_API_KEY
docker compose up --build
```

UI on :3000, API on :8000. Changing `BACKEND_PORT` needs `--build`, since the URL is baked into the frontend bundle.
