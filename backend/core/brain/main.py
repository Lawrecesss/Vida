import os
import dotenv
from langchain_openrouter import ChatOpenRouter
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate

dotenv.load_dotenv()

# 1. Initialize the OpenRouter model
brain = ChatOpenRouter(
    model="google/gemma-4-26b-a4b-it:free",
    openrouter_api_key=os.getenv("OPENROUTER_API_KEY"),
    temperature=0,
    seed=42
)

# 2. Define your tools and prompt
hands = [...] 
prompt = ChatPromptTemplate.from_messages([
    ("system", "You are the brain of the program. You need to decide which tool to use to answer the user's question. You have access to the following tools: {tools}. When you want to use a tool, you should call it with the appropriate input. If you need to think step by step, you can use the scratchpad to write down your thoughts."),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}"),
])

# 3. Create the agent
agent = create_tool_calling_agent(brain, hands, prompt)

# 4. Execute
agent_executor = AgentExecutor(agent=agent, tools=hands, verbose=True)
agent_executor.invoke({"input": "What is the weather in Tokyo?"})
