import json
from typing import Any

from datetime import datetime
from pydantic import BaseModel, Field, field_validator
from schemas.message import MessageRead


_TAG_KEYS: tuple[str, ...] = (
    "has_frontend",
    "has_backend",
    "is_script",
    "is_mobile_app",
    "is_devops_program",
    "is_full_stack",
    "has_mixed_technologies",
)


def normalize_project_tags(
    value: Any,
    *,
    require_any_true: bool = False,
) -> dict[str, bool] | None:
    """Normalize legacy project_tags shapes into the canonical tag dict."""
    if value is None:
        return None

    parsed = value
    if isinstance(parsed, str):
        parsed = parsed.strip()
        if not parsed:
            return None
        try:
            parsed = json.loads(parsed)
        except json.JSONDecodeError:
            return None

    normalized: dict[str, bool] = {key: False for key in _TAG_KEYS}

    if isinstance(parsed, dict):
        for key in _TAG_KEYS:
            if key in parsed:
                normalized[key] = bool(parsed[key])
    elif isinstance(parsed, list):
        for key in parsed:
            if key in normalized:
                normalized[key] = True
    else:
        return None

    normalized["is_full_stack"] = (
        normalized["has_frontend"] and normalized["has_backend"]
    )
    if normalized["has_frontend"] or normalized["has_backend"]:
        normalized["is_script"] = False

    if require_any_true and not any(normalized.values()):
        return None

    return normalized


class ConversationCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=3000)


class ConversationRead(BaseModel):
    id: int
    idea_id: int
    status: str
    project_tags:     dict[str, bool] | None = None
    github_repo_name: str | None = None
    github_repo_url:  str | None = None
    deployment_status:   str = "not_deployed"
    deployment_live_url: str | None = None
    deployment_error:    str | None = None
    jira_project_key: str | None = None
    jira_project_url: str | None = None
    created_at: datetime

    @field_validator("project_tags", mode="before")
    @classmethod
    def _normalize_project_tags(cls, value: Any) -> dict[str, bool] | None:
        return normalize_project_tags(value, require_any_true=True)

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
    jira_tickets_created:  list[dict]           = Field(default_factory=list)
    jira_error:            str | None           = None
