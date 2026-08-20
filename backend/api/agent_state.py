"""Lazy singleton for the optional agent layer."""

from __future__ import annotations

from fastapi import HTTPException

from api.deps import get_vida

_agent = None


def get_agent():
    """Build the agent on first use, with a clear error if extras are missing."""
    global _agent
    if _agent is None:
        try:
            from vida.agent import VidaAgent
        except ImportError as exc:
            raise HTTPException(
                status_code=501,
                detail="The chat agent is not installed. Run: pip install 'vida-sdk[agent]'",
            ) from exc

        from vida.errors import ConfigurationError, MissingDependencyError

        try:
            _agent = VidaAgent(get_vida())
        except (MissingDependencyError, ConfigurationError) as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from exc

    return _agent


async def close_agent() -> None:
    global _agent
    _agent = None
