from langchain_openrouter import ChatOpenRouter
from langchain_core.messages import HumanMessage
import os
import dotenv

VIDEO_MODEL = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"
# deepseek/deepseek-v4-flash:free
# arcee-ai/trinity-large-thinking:free
REASONING_MODEL = "arcee-ai/trinity-large-thinking:free"
OVERLAP = 2
TEMPERATURE = 0.2

dotenv.load_dotenv("./.env.secret", override=True)
def _make_client(model: str, **kwargs) -> ChatOpenRouter:
    return ChatOpenRouter(
        model=model,
        temperature=TEMPERATURE,
        api_key=os.getenv("OPENROUTER_API_KEY"),
        **kwargs,
    )

AGENT_MODEL = _make_client(REASONING_MODEL, reasoning={"enabled": True})

async def video_analysis_model_with_reasoning(content):
    client = _make_client(
        VIDEO_MODEL,
        reasoning={"enabled": True},
        model_kwargs={
            "provider": {"quantization": ["int8"]},
        }
    )
    return await client.ainvoke([HumanMessage(content=content)])

async def video_analysis_model_without_reasoning(content):
    client = _make_client(
        VIDEO_MODEL,
        reasoning={"enabled": False},
        model_kwargs={
            "provider": {"quantization": ["int8"]},
        }
    )
    return await client.ainvoke([HumanMessage(content=content)])

async def reasoning_model_response(timeline: str, user_query: str = None):
    client = _make_client(
        REASONING_MODEL,
        reasoning={"enabled": True},
    )
    prompt = f"Reconstruct the narrative:\n\n{timeline}\n\nQuestion: {user_query or 'Summary'}"
    return await client.ainvoke([HumanMessage(content=prompt)])