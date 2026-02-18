import enum
from datetime import datetime
from typing import List, Optional, Dict, Annotated

from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = ""


class ChatResponse(BaseModel):
    message :str
    session_id :str
    conversation_title :str

class MessageRole(str, enum.Enum):
    USER = "user"
    AI = "ai"

class Message(BaseModel):
    role :MessageRole
    content :str
    files: Optional[List[Dict]] = Field(default=None, description="存储字典的列表，前端可解析的后端文件响应")
class Conversation(BaseModel):
    """
    与智能体对话存放model
    """
    session_id :str
    title :str = "新对话"
    messages :List[Message] = []
    created_at :datetime = Field(default_factory=datetime.now) # 要求传入的是函数方法
    updated_at :datetime = Field(default_factory=datetime.now)

class ConversationListResp(BaseModel):
    total: int = Field(default=0, description="会话总数")
    limit: int = Field(default=10, description="本次返回条数")
    conversations: List[Conversation] = Field(default=[], description="会话列表")

