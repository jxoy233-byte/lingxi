from typing import TypedDict, Annotated

from langgraph.graph import add_messages
from langchain_core.messages import BaseMessage

class ChatState(TypedDict):
    """State for the chatMe graph"""
    messages: Annotated[list[BaseMessage], add_messages]