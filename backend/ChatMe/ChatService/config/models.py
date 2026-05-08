from enum import Enum
from datetime import datetime
from typing import List, Optional, Dict

from pydantic import BaseModel, Field

from ChatMe.ChatService.FilesLoaders.core import OutputFormat


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = ""
    processed_outputs: Optional[List[OutputFormat]] = None


class ChatResponse(BaseModel):
    message :str
    session_id :str
    conversation_title :str

class MessageRole(str, Enum):
    USER = "user"
    AI = "ai"

class Message(BaseModel):
    role: MessageRole
    content: Optional[str]
    files: Optional[List[Dict]] = Field(default=None, description="存储字典的列表，前端可解析的后端文件响应")
    additional_kwargs: Optional[Dict]

class Conversation(BaseModel):
    """
    与智能体对话存放model
    """
    session_id :str
    title :str = "新对话"
    messages :List[Message] = []
    created_at :datetime = Field(default_factory=datetime.now) # 要求传入的是函数方法
    updated_at :datetime = Field(default_factory=datetime.now)
    is_interrupted: bool = False

class ConversationListResp(BaseModel):
    total: int = Field(default=0, description="会话总数")
    limit: int = Field(default=10, description="本次返回条数")
    conversations: List[Conversation] = Field(default=[], description="会话列表")

class ConversationSimple(BaseModel):
    """简化版会话列表项，仅包含ID、标题和更新时间"""
    session_id: str
    title: str = "新对话"
    updated_at: Optional[datetime] = Field(default=None)

