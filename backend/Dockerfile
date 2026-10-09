# syntax=docker/dockerfile:1
# Build context is the repo root, not backend/: the core library is installed
# from ./core, so it has to be inside the context (compose.yaml sets it).
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

# After the dependencies so editing the library doesn't reinstall FastAPI.
COPY core/ ./core/
RUN pip install ./core

COPY backend/app ./app

RUN useradd --create-home --uid 1000 vida
USER vida
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
