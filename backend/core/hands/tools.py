from langchain.pydantic_v1 import BaseModel, Field

class SearchInput(BaseModel):
    query: str = Field(description="The search query to look up")
    limit: int = Field(description="Number of results to return", default=5)

@tool("web_search_tool", args_schema=SearchInput)
def web_search_tool(query: str, limit: int):
    """Search for news with a specific result limit."""
    return f"Searching for {query} (returning {limit} results)"

tools = [web_search_tool]