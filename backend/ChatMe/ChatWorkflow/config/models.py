from operator import add
from typing import TypedDict, Annotated, List, Optional, Dict, Any

from langgraph.graph import add_messages
from langchain_core.messages import BaseMessage, HumanMessage
from pydantic import BaseModel
from enum import Enum

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


class ChatStateCore2(TypedDict):
    """State for the ChatMe graph2"""
    messages: Annotated[list[BaseMessage], add_messages]
    imp_ipt: Annotated[HumanMessage, "优化后的用户输入"]
    context: Annotated[Optional[List[BaseMessage]], "与上下文拼接好了的用户输入信息，含记忆"]

    tool_call_times: Annotated[int, "当前轮对话中调用工具次数"]

    # memory 累加字段（各节点各自填充）
    memory_user_message: Annotated[Optional[str], "待写入memory的用户消息"]
    memory_ai_response: Annotated[Optional[str], "待写入memory的AI回复"]
    memory_tool_calls: Annotated[List[Dict[str, Any]], "待写入memory的工具调用"]
    memory_tool_results: Annotated[List[str], "待写入memory的工具结果"]
    should_end_decision: Annotated[Optional[str], "should_end_node 的决策结果，end 或 retry"]
    should_end_retry_times: Annotated[int, "should_end_node 连续 retry 的次数，超过3次强制跳 final_node"]

    # ReAct 流程压缩：context_assembly_node 中按 tool_call 节拍整体覆盖
    context_summary_text: Annotated[Optional[str], "ReAct 压缩产物的纯文本；context_assembly_node 中按阈值整体覆盖更新"]
    last_compact_at_tool_calls: Annotated[int, "上一次成功 ReAct 压缩时的 tool_call_times；用于防 state 恢复或失败后重复触发"]


class AIMessageType(str, Enum):
    """AIMessage区分消息类型的枚举类"""
    REASONING = "REASONING"
    SUMMARY = "SUMMARY"


class FileParseState(TypedDict):
    messages: List[BaseMessage]
    files: List[List[dict]]  # 拆分出的文件消息
    parsed_results: Annotated[List[str], add]  # 各节点解析结果
    combined_result: HumanMessage  # 汇总结果