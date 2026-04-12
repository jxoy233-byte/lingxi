from typing import TypedDict, Annotated, List, Optional

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
    history_summary: Annotated[Optional[BaseMessage], "对于长历史上下文的历史对话总结"]
    summary_or_not: Annotated[bool, "是否需要历史上下文总结"]
    has_file_or_not_cur: Annotated[bool, "本轮对话是否包含文件"]
    tool_call_times: Annotated[int, "当前轮对话中调用工具次数"]

class AIMessageType(str, Enum):
    """AIMessage区分消息类型的枚举类"""
    REASONING = "REASONING"
    SUMMARY = "SUMMARY"