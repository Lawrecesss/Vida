"""FastAPI application wrapping the Vida SDK."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.deps import close_vida
from api.router import router
from vida import __version__


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    await close_vida()


app = FastAPI(title="Vida API", version=__version__, lifespan=lifespan)

# Comma-separated origins, e.g. "https://app.example.com,https://admin.example.com".
# Defaults to the local Next.js dev server rather than "*", which would let any
# site on the internet call this API from a user's browser.
_origins = [
    origin.strip()
    for origin in os.getenv("VIDA_CORS_ORIGINS", "http://localhost:3000").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": __version__}
