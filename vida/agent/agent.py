"""An optional natural-language agent over the SDK.

Install with ``pip install 'vida-sdk[agent]'``. The core SDK does not import this
module, so LangGraph stays out of the fast path.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from vida.agent.tools import build_tools
from vida.client import Vida
from vida.config import VidaConfig
from vida.errors import ConfigurationError, MissingDependencyError

__all__ = ["VidaAgent"]

SYSTEM_PROMPT = """You help users understand video files.

You have tools that analyze what a video shows, transcribe what is said in it, \
and translate that speech into other languages.

Guidelines:
- Pick the tool that matches the question. "What happens in this video?" is \
analysis; "what did they say?" is transcription.
- Videos can be long. Call a tool once and work from its result rather than \
calling it repeatedly.
- If a tool reports an error, tell the user plainly what failed. Do not invent \
content you did not receive.
- Answer directly and concisely. Do not describe your tool calls."""


class VidaAgent:
    """A conversational wrapper around the SDK's tools."""

    def __init__(
        self,
        vida: Vida | None = None,
        *,
        model: str | None = None,
        config: VidaConfig | None = None,
        system_prompt: str = SYSTEM_PROMPT,
    ) -> None:
        config = config or (vida.config if vida else VidaConfig())
        if not config.openrouter_api_key:
            raise ConfigurationError("OPENROUTER_API_KEY is required for the agent.")

        try:
            from langchain_openrouter import ChatOpenRouter
            from langgraph.prebuilt import create_react_agent
        except ImportError as exc:  # pragma: no cover - optional extra
            raise MissingDependencyError("langgraph / langchain-openrouter", "agent") from exc

        self.vida = vida or Vida(config)
        self.model_name = model or config.analysis.synthesis_model

        llm = ChatOpenRouter(
            model=self.model_name,
            temperature=0.2,
            api_key=config.openrouter_api_key,
        )
        self._graph = create_react_agent(
            model=llm,
            tools=build_tools(self.vida),
            prompt=system_prompt,
        )

    async def run(self, message: str) -> str:
        """Answer one message and return the final text."""
        from langchain_core.messages import HumanMessage

        state = await self._graph.ainvoke({"messages": [HumanMessage(content=message)]})
        return state["messages"][-1].content

    async def stream(self, message: str) -> AsyncIterator[str]:
        """Answer one message, yielding text as the model produces it."""
        from langchain_core.messages import HumanMessage

        async for event in self._graph.astream_events(
            {"messages": [HumanMessage(content=message)]}, version="v2"
        ):
            if event["event"] == "on_chat_model_stream":
                chunk = event["data"]["chunk"].content
                if chunk:
                    yield chunk

    async def aclose(self) -> None:
        await self.vida.aclose()

    async def __aenter__(self) -> VidaAgent:
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.aclose()
