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


class TaskingResult(BaseModel):
    """
    Returned by POST /conversations/{id}/start-tasking.

    Extends ConversationDetail with the outcome of the ticket-generation phase:
    - tickets:              the full ticket payload from the PM agent (or None)
    - jira_tickets_created: list of Jira issues that were actually created
    - jira_error:           non-None when Jira is connected but the push failed
    """
    conversation:          ConversationRead
    messages:              list[MessageRead]
    tickets:               dict | None          = None
    jira_tickets_created:  list[dict]           = []
    jira_error:            str | None           = None
