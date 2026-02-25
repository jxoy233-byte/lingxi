from typing import TypedDict, Annotated, List

from langgraph.graph import add_messages
from langchain_core.messages import BaseMessage
from pydantic import BaseModel


class SearchDecision(BaseModel):
    should_search: bool = False
    query: str = ""
    
    def __init__(self, should_search: bool, query: str):
        super().__init__()
        self.should_search = should_search
        self.query = query

class ChatStateCore(TypedDict):
    """State for the chatMe graph3"""
    messages: Annotated[list[BaseMessage], add_messages]
    search_decision: Annotated[SearchDecision, "每一轮对话的搜索判断结果"]
    search_message: Annotated[List, "每一轮对话的搜索结果"]
