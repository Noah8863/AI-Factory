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
    priority:        str | None
    title:           str
    status:          str
    error_msg:       str | None
    created_at:      datetime
    updated_at:      datetime

    model_config = {"from_attributes": True}


class AgentRunResponse(BaseModel):
    conversation_id: int
    done:            int
    failed:          int
    still_pending:   int
    deployment_status:   str | None = None
    deployment_live_url: str | None = None
    deployment_error:    str | None = None
    tickets:         list[TicketRead]
