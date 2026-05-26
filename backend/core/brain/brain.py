import warnings
warnings.filterwarnings("ignore", message=".*allowed_objects.*")

from langchain_core.messages import HumanMessage
from langgraph.prebuilt import create_react_agent
from core.hands.video_analyzer import video_analyzer
from core.models.models import AGENT_MODEL

agent = create_react_agent(
    model=AGENT_MODEL,
    tools=[video_analyzer],
)

async def run_agent(user_message: str):
    response = await agent.ainvoke({
        "messages": [HumanMessage(content=user_message)]
    })
    return response["messages"][-1].content

async def run_agent_stream(user_message: str):
    async for event in agent.astream_events(
        {"messages": [HumanMessage(content=user_message)]},
        version="v2"
    ):
        if event["event"] == "on_chat_model_stream":
            chunk = event["data"]["chunk"].content
            if chunk:
                yield chunk