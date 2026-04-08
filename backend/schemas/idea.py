from datetime import datetime
from pydantic import BaseModel, Field


class IdeaCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=3000)


class IdeaRead(BaseModel):
    id: int
    content: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}
