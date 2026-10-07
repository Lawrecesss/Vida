# syntax=docker/dockerfile:1

# The build context is the REPO ROOT, not backend/. requirements.txt installs
# the SDK with `-e ../`, so vida/ and pyproject.toml have to be inside the
# context — compose.yaml sets `context: .` for exactly that reason, and a bare
# `docker build backend/` cannot work.

FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Only what the install itself reads, so editing the frontend or the evals does
# not invalidate this layer. README.md is here because pyproject.toml names it
# as the project readme and hatchling opens it while building the SDK.
WORKDIR /app
COPY pyproject.toml README.md ./
COPY vida/ ./vida/
COPY backend/requirements.txt ./backend/requirements.txt

# Installed from backend/, so the `-e ../` inside requirements.txt lands on /app
# whether pip resolves it against the file or against the working directory.
WORKDIR /app/backend
RUN pip install -r requirements.txt


FROM python:3.12-slim AS runtime

# A system ffmpeg is preferred over the imageio-ffmpeg fallback, and it is the
# only way to get ffprobe at all: imageio-ffmpeg ships no ffprobe, which drops
# vida/media/ffmpeg.py onto its slower `ffmpeg -i` stderr parse for every probe.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    VIDA_UPLOAD_DIR=/data/uploads

COPY --from=builder /opt/venv /opt/venv

# The SDK went in editable, so its source has to sit at the same path it had at
# build time — /app — or the .pth left in site-packages points at nothing.
WORKDIR /app
COPY pyproject.toml README.md ./
COPY vida/ ./vida/
COPY backend/ ./backend/

# Uploads live on a volume. Creating the directory here with the right owner is
# what makes Docker hand a fresh named volume to a non-root process already
# chowned, rather than root-owned and unwritable.
RUN useradd --create-home --uid 1000 vida \
 && mkdir -p /data/uploads \
 && chown -R vida:vida /data /app

USER vida
WORKDIR /app/backend
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

# One worker, deliberately: api/deps.py and api/agent_state.py both hold
# process-wide singletons (the pooled Vida client, the LangGraph agent), so a
# second worker buys a second connection pool and a second agent, not throughput.
CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8000"]
