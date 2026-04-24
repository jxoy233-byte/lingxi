from typing import TypedDict, Annotated, List, Optional, Dict, Any, Literal

from langgraph.graph import add_messages
from langchain_core.messages import BaseMessage, HumanMessage
from pydantic import BaseModel
from enum import Enum


class SearchDecision(BaseModel):
    should_search: bool = False
    query: str = ""

    def __init__(self, should_search: bool, query: str):
        super().__init__()
        self.should_search = should_search
        self.query = query


class MemoryUpdateFormat(BaseModel):
    """记忆更新所需的数据结构"""
    user_message: str = ""
    ai_response: str = ""
    tool_calls: List[Dict[str, Any]] = []
    tool_results: List[str] = []

    def __init__(self, user_message: str, ai_response: str, tool_calls: List[Dict[str, Any]], tool_results: List[str]):
        super().__init__()
        self.user_message = user_message
        self.ai_response = ai_response
        self.tool_calls = tool_calls
        self.tool_results = tool_results


class ChatStateCore(TypedDict):
    """State for the ChatMe graph"""
    messages: Annotated[list[BaseMessage], add_messages]
    history_summary: Annotated[Optional[BaseMessage], "对于长历史上下文的历史对话总结"]
    summary_or_not: Annotated[bool, "是否需要历史上下文总结"]
    has_file_or_not_cur: Annotated[bool, "本轮对话是否包含文件"]
    tool_call_times: Annotated[int, "当前轮对话中调用工具次数"]


class ChatStateCore2(TypedDict):
    """State for the ChatMe graph2"""
    messages: Annotated[list[BaseMessage], add_messages]
    imp_ipt: Annotated[HumanMessage, "优化后的用户输入"]
    context: Annotated[Optional[List[BaseMessage]], "与上下文拼接好了的用户输入信息，含记忆"]

    restream_checkpoint_id :Annotated[str, "重新开始会话的回溯checkpoint id"]
    tool_call_times: Annotated[int, "当前轮对话中调用工具次数"]

    # memory 累加字段（各节点各自填充）
    memory_user_message: Annotated[Optional[str], "待写入memory的用户消息"]
    memory_ai_response: Annotated[Optional[str], "待写入memory的AI回复"]
    memory_tool_calls: Annotated[List[Dict[str, Any]], "待写入memory的工具调用"]
    memory_tool_results: Annotated[List[str], "待写入memory的工具结果"]


class AIMessageType(str, Enum):
    """AIMessage区分消息类型的枚举类"""
    REASONING = "REASONING"
    SUMMARY = "SUMMARY"