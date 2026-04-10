from datetime import datetime
from pydantic import BaseModel


class JiraTokenCreate(BaseModel):
    """Payload used internally (e.g. from OAuth callback) to upsert a token."""
    access_token:  str
    refresh_token: str | None = None
    expires_at:    datetime


class JiraTokenRead(BaseModel):
    """Safe read model — never exposes raw token values to the client."""
    id:         int
    user_id:    int
    expires_at: datetime
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class JiraTokenUpsert(BaseModel):
    """Used to replace/refresh stored tokens (e.g. after a token refresh)."""
    access_token:  str
    refresh_token: str | None = None
    expires_at:    datetime
