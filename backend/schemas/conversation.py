from datetime import datetime
from pydantic import BaseModel, Field
from schemas.message import MessageRead


class ConversationCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=3000)


class ConversationRead(BaseModel):
    id: int
    idea_id: int
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationDetail(BaseModel):
    conversation: ConversationRead
    messages: list[MessageRead]
