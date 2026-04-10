from datetime import datetime
from typing import Literal
from pydantic import BaseModel


class UserSettingsRead(BaseModel):
    id: int
    user_id: int
    theme: str
    notifications_enabled: bool
    updated_at: datetime

    model_config = {"from_attributes": True}


class UserSettingsUpdate(BaseModel):
    theme: Literal["light", "dark"] | None = None
    notifications_enabled: bool | None = None
