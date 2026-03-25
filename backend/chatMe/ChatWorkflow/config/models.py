from typing import TypedDict, Annotated, List

from langgraph.graph import add_messages
from langchain_core.messages import BaseMessage
from pydantic import BaseModel
from enum import Enum

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

class AIMessageType(str, Enum):
    """AIMessage区分消息类型的枚举类"""
    REASONING = "REASONING"
    SUMMARY = "SUMMARY"