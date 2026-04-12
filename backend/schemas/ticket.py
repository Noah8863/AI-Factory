from datetime import datetime
from pydantic import BaseModel


class TicketRead(BaseModel):
    id:              int
    conversation_id: int
    ticket_id:       str
    jira_issue_key:  str | None
    type:            str
    phase:           str | None
    sequence:        int | None
    depends_on:      list[str]
    priority:        str | None
    title:           str
    description:     str
    story_points:    int | None
    labels:          list[str]
    status:          str
    error_msg:       str | None
    agent_output:    str | None
    created_at:      datetime
    updated_at:      datetime

    model_config = {"from_attributes": True}


class AgentRunResponse(BaseModel):
    conversation_id: int
    done:            int
    failed:          int
    still_pending:   int
    tickets:         list[TicketRead]
