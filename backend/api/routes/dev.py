"""
Temporary developer-testing routes.
These endpoints bypass the normal agent flow and are used to validate
individual capabilities (e.g. GitHub repo creation) in isolation.

TODO: Remove this file before shipping to production.
"""
import logging
import os
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.database import get_db
from models.conversation import Conversation
from models.idea import Idea
from models.ticket import Ticket
from services import pm_agent as pm_agent_service
from services.agent_runner import store_tickets
from services.github_service import create_org_repo

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dev", tags=["dev"])


class CreateRepoRequest(BaseModel):
    repo_name: str = "test-repo"


class CreateRepoResponse(BaseModel):
    repo_url: str
    repo_name: str
    already_existed: bool


class ScriptCoercionTestResponse(BaseModel):
    ok: bool
    normalized_types: list[str]
    stored_types: list[str]
    ticket_count: int


@router.post("/create-github-repo", response_model=CreateRepoResponse)
def dev_create_github_repo(payload: CreateRepoRequest):
    """
    [DEV] Directly trigger GitHub org-repo creation without going through the
    PM agent flow. Useful for testing the GitHub token and org permissions.
    """
    logger.info(f"[DEV] create-github-repo called with repo_name={payload.repo_name!r}")

    result = create_org_repo(payload.repo_name)
    if result is None:
        token_set = bool(os.getenv("GITHUB_TOKEN"))
        raise HTTPException(
            status_code=502,
            detail=f"GitHub API call failed. GITHUB_TOKEN present={token_set}. Check token permissions and org settings.",
        )

    return CreateRepoResponse(
        repo_url=result["url"],
        repo_name=payload.repo_name,
        already_existed=not result["created"],
    )


@router.post("/assert-script-ticket-coercion", response_model=ScriptCoercionTestResponse)
def dev_assert_script_ticket_coercion(
    db: Session = Depends(get_db),
):
    """
    [DEV] Integration test path for script project coercion.

    It validates that script-tagged tasking output is normalized to
    ticket type 'script' before storage and remains 'script' after
    persistence via store_tickets().
    """
    sample_payload = {
        "projectName": "Script Coercion Probe",
        "projectSummary": "Validates ticket-type coercion behavior.",
        "githubRepoName": "script-coercion-probe",
        "jiraProjectKey": "SCP",
        "projectTags": {
            "has_frontend": False,
            "has_backend": False,
            "is_script": True,
            "is_mobile_app": False,
            "is_devops_program": False,
            "is_full_stack": False,
            "has_mixed_technologies": False,
        },
        "tickets": [
            {
                "id": "BE-1",
                "type": "backend",
                "title": "Create Python entry script",
                "description": "Create a Python CLI entrypoint that prints a greeting.",
                "priority": "High",
                "phase": "Core",
                "sequence": 1,
                "dependsOn": [],
                "storyPoints": 1,
                "labels": ["is_script"],
            },
            {
                "id": "FE-1",
                "type": "frontend",
                "title": "Add shell runner",
                "description": "Add a shell wrapper that invokes the Python entry script.",
                "priority": "Medium",
                "phase": "Core",
                "sequence": 2,
                "dependsOn": ["BE-1"],
                "storyPoints": 1,
                "labels": ["is_script"],
            },
        ],
    }

    normalized_payload = pm_agent_service.normalize_tasking_payload_for_storage(
        tickets_payload=sample_payload,
        project_tags=sample_payload.get("projectTags"),
    )
    if not normalized_payload:
        raise HTTPException(status_code=500, detail="Failed to normalize script test payload.")

    normalized_types = [
        (t.get("type") or "")
        for t in normalized_payload.get("tickets", [])
        if isinstance(t, dict)
    ]
    if not normalized_types or any(ticket_type != "script" for ticket_type in normalized_types):
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Normalization failed before storage; expected all ticket types to be 'script'.",
                "normalized_types": normalized_types,
            },
        )

    idea: Idea | None = None
    conversation: Conversation | None = None
    stored_types: list[str] = []

    try:
        idea = Idea(content="[DEV] script coercion integration probe")
        db.add(idea)
        db.flush()

        conversation = Conversation(
            idea_id=idea.id,
            status="tasking",
            project_tags=normalized_payload.get("projectTags"),
        )
        db.add(conversation)
        db.flush()
        db.commit()
        db.refresh(conversation)

        stored_rows = store_tickets(
            conversation_id=conversation.id,
            tickets_data=normalized_payload,
            jira_results=[],
            db=db,
        )
        stored_types = [row.type for row in stored_rows]

        if not stored_types or any(ticket_type != "script" for ticket_type in stored_types):
            raise HTTPException(
                status_code=500,
                detail={
                    "message": "Storage validation failed; expected all persisted ticket types to be 'script'.",
                    "stored_types": stored_types,
                },
            )

        return ScriptCoercionTestResponse(
            ok=True,
            normalized_types=normalized_types,
            stored_types=stored_types,
            ticket_count=len(stored_types),
        )
    finally:
        if conversation is not None:
            db.query(Ticket).filter(Ticket.conversation_id == conversation.id).delete(
                synchronize_session=False,
            )
            db.query(Conversation).filter(Conversation.id == conversation.id).delete(
                synchronize_session=False,
            )
        if idea is not None:
            db.query(Idea).filter(Idea.id == idea.id).delete(synchronize_session=False)
        db.commit()
