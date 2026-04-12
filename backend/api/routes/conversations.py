import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from db.database import get_db
from models.conversation import Conversation
from models.idea import Idea
from models.jira_token import JiraToken
from models.message import Message
from schemas.conversation import (
    ConversationCreate,
    ConversationDetail,
    ConversationRead,
    TaskingResult,
)
from schemas.message import MessageCreate, MessageRead
from services import pm_agent
from services.agent_runner import store_tickets, run_all_tickets_bg
from services.github_service import create_org_repo
from services.jira_service import create_jira_project, push_tickets_to_jira, JiraServiceError
from models.user import User
from services.auth_service import SECRET_KEY, ALGORITHM, get_current_user

logger = logging.getLogger(__name__)

# ── Post-tasking agent messages (stored in DB, shown in chat) ────────────────
TASKING_COMPLETE_AGENT_MESSAGE = (
    "Jira tickets have been made! I'll start tasking out these requirements to an "
    "AI agent. Would you like to continue defining the scope?"
)
TASKING_DECLINED_AGENT_MESSAGE = (
    "Sounds good! If you need any additional requirements handled, come back and "
    "click on the 'Add more requirements' button on the bottom to start chatting "
    "with me again."
)

# Optional bearer: does not raise 401 when the header is absent, so
# unauthenticated callers can still use conversations (Jira is simply skipped).
_optional_bearer = HTTPBearer(auto_error=False)

router = APIRouter(prefix="/conversations", tags=["conversations"])

JIRA_REQUIRED_MESSAGE = "Please connect your Jira account before making a project."


def _get_owned_conversation(
    conversation_id: int,
    user_id: int,
    db: Session,
) -> Conversation:
    conversation = (
        db.query(Conversation)
        .join(Idea, Conversation.idea_id == Idea.id)
        .filter(Conversation.id == conversation_id, Idea.user_id == user_id)
        .first()
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


def _ensure_jira_connected(user_id: int, db: Session) -> None:
    connected = db.query(JiraToken).filter(JiraToken.user_id == user_id).first() is not None
    if not connected:
        raise HTTPException(status_code=403, detail=JIRA_REQUIRED_MESSAGE)


def _build_detail(conversation: Conversation, db: Session) -> ConversationDetail:
    messages = (
        db.query(Message)
        .filter(Message.conversation_id == conversation.id)
        .order_by(Message.created_at)
        .all()
    )
    return ConversationDetail(
        conversation=ConversationRead.model_validate(conversation),
        messages=[MessageRead.model_validate(m) for m in messages],
    )


def _build_llm_history(messages: list[Message]) -> list[dict]:
    """
    Converts stored DB messages to the role/content format expected by the LLM.
    The agent role is stored as "agent" in the DB but the LLM expects "assistant".
    """
    return [
        {
            "role": "assistant" if m.role == "agent" else "user",
            "content": m.content,
        }
        for m in messages
    ]


@router.post("", response_model=ConversationDetail, status_code=201)
def create_conversation(
    payload: ConversationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Creates an idea, a conversation, the user's opening message,
    and the PM agent's first clarifying response — all in one shot.
    """
    _ensure_jira_connected(current_user.id, db)

    # 1. Persist the idea (associated with the logged-in user)
    idea = Idea(content=payload.content, user_id=current_user.id)
    db.add(idea)
    db.flush()

    # 2. Open a conversation
    conversation = Conversation(idea_id=idea.id)
    db.add(conversation)
    db.flush()

    # 3. Store user's opening message
    db.add(Message(
        conversation_id=conversation.id,
        role="user",
        content=payload.content,
    ))
    db.flush()

    # 4. PM agent reads the idea and asks its first clarifying question
    agent_reply = pm_agent.get_initial_message(payload.content)
    db.add(Message(
        conversation_id=conversation.id,
        role="agent",
        content=agent_reply,
    ))

    db.commit()
    db.refresh(conversation)
    return _build_detail(conversation, db)


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: int, db: Session = Depends(get_db)):
    conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return _build_detail(conversation, db)


@router.post("/{conversation_id}/messages", response_model=ConversationDetail)
def send_message(
    conversation_id: int,
    payload: MessageCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Appends a user message, calls the PM agent with the full conversation
    history, and returns the updated thread.
    """
    _ensure_jira_connected(current_user.id, db)
    conversation = _get_owned_conversation(conversation_id, current_user.id, db)
    if conversation.status in ("tasking", "done"):
        raise HTTPException(status_code=400, detail="Conversation is not open for new messages.")

    # Store the new user message
    db.add(Message(
        conversation_id=conversation_id,
        role="user",
        content=payload.content,
    ))
    db.flush()

    # Fetch the full history (including the message just flushed)
    all_messages = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
        .all()
    )

    user_count = sum(1 for m in all_messages if m.role == "user")
    llm_history = _build_llm_history(all_messages)

    # Call PM agent service with full history
    response_text, is_ready, _tickets = pm_agent.get_pm_response(llm_history, user_count)

    db.add(Message(
        conversation_id=conversation_id,
        role="agent",
        content=response_text,
    ))

    if is_ready and conversation.status == "active":
        conversation.status = "ready_to_task"

    db.commit()
    db.refresh(conversation)
    return _build_detail(conversation, db)


@router.post("/{conversation_id}/start-tasking", response_model=TaskingResult)
async def start_tasking(
    conversation_id: int,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Triggers the PM agent's ticket-generation phase for this conversation:

    1. Sends the standard "ACTION: Start tasking" trigger message to the LLM.
    2. Stores both the trigger message and the agent's JSON reply in the DB.
    3. Parses the ticket JSON from the reply.
    4. If the caller is authenticated and has Jira connected, creates tickets
       in their Jira project.  Jira failures are non-fatal — the conversation
       still transitions to 'tasking'.
    5. Returns TaskingResult with the updated conversation, full message
       history, ticket payload, and Jira creation results.
    """
    _ensure_jira_connected(current_user.id, db)
    conversation = _get_owned_conversation(conversation_id, current_user.id, db)

    if conversation.status in ("tasking", "done"):
        raise HTTPException(status_code=400, detail="Conversation is not in a taskable state.")

    user_id = current_user.id

    # ── Load all messages, then slice to post-checkpoint window ──
    # On a re-tasking run the user has already had one round of ticket generation.
    # We find the last "ACTION: Start tasking" trigger in the stored messages and
    # use only messages that came AFTER it (plus the confirmation reply that
    # immediately followed), so the PM only sees NEW requirements — not the
    # original ones that were already ticketed.
    existing_messages = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
        .all()
    )

    last_action_idx: int | None = None
    for i, msg in enumerate(existing_messages):
        if msg.role == "user" and msg.content == pm_agent.TASKING_ACTION_MESSAGE:
            last_action_idx = i

    if last_action_idx is not None:
        # Skip the trigger message (+1) and the agent reply that followed it (+2)
        checkpoint_messages = existing_messages[last_action_idx + 2:]
    else:
        checkpoint_messages = existing_messages

    llm_history = _build_llm_history(checkpoint_messages)

    # ── Call PM agent — generates ticket JSON ────────────────────
    result = await pm_agent.run_tasking(history=llm_history)

    tickets_data = result.get("tickets") or {}

    # ── 1. Create GitHub repo (first tasking only) ───────────────
    if conversation.github_repo_url is None:
        repo_name = tickets_data.get("githubRepoName")
        if repo_name:
            repo_result = create_org_repo(repo_name)
            if repo_result:
                conversation.github_repo_name = repo_name
                conversation.github_repo_url  = repo_result["url"]
                logger.info(
                    "GitHub repo %r created for conversation %s: %s",
                    repo_name, conversation_id, repo_result["url"],
                )
            else:
                logger.warning(
                    "GitHub repo creation failed for conversation %s (repo_name=%r).",
                    conversation_id, repo_name,
                )
        else:
            logger.warning(
                "start_tasking: PM agent did not return a githubRepoName for "
                "conversation %s — skipping repo creation.",
                conversation_id,
            )

    # ── 2. Resolve Jira project from user's profile selection ────
    # (Auto-create logic is temporarily disabled — see commented block below)
    jira_cloud_id:        str | None = None
    jira_tickets_created: list[dict] = []
    jira_error:           str | None = None

    if conversation.jira_project_key is None:
        token_row = db.query(JiraToken).filter(JiraToken.user_id == user_id).first()
        if token_row and token_row.jira_project_key:
            conversation.jira_project_key = token_row.jira_project_key
            jira_cloud_id = token_row.jira_cloud_id
            logger.info(
                "Using user-selected Jira project '%s' for conversation %s.",
                token_row.jira_project_key, conversation_id,
            )
        else:
            jira_error = (
                "No Jira project selected. Please choose a target project "
                "in your Profile settings before starting a build."
            )
            logger.warning(
                "start_tasking: no Jira project selected for user %s (conversation %s).",
                user_id, conversation_id,
            )

    # ── AUTO-CREATE (disabled — re-enable when Jira scope issues are resolved) ──
    # if conversation.jira_project_key is None:
    #     raw_project_key = tickets_data.get("jiraProjectKey")
    #     project_name    = tickets_data.get("projectName", "AI Factory Project")
    #     if raw_project_key:
    #         try:
    #             proj_result = await create_jira_project(
    #                 user_id=user_id,
    #                 db=db,
    #                 project_key=raw_project_key,
    #                 project_name=project_name,
    #             )
    #             conversation.jira_project_key = proj_result["project_key"]
    #             conversation.jira_project_url = proj_result["project_url"]
    #             jira_cloud_id = proj_result["cloud_id"]
    #             logger.info(
    #                 "Jira project %r created for conversation %s: %s",
    #                 proj_result["project_key"], conversation_id, proj_result["project_url"],
    #             )
    #         except JiraServiceError as exc:
    #             jira_error = f"Jira project creation failed: {exc}"
    #             logger.warning(
    #                 "Jira project creation failed for conversation %s: %s",
    #                 conversation_id, exc,
    #             )
    #     else:
    #         logger.warning(
    #             "start_tasking: PM agent did not return a jiraProjectKey for "
    #             "conversation %s — skipping Jira project creation.",
    #             conversation_id,
    #         )

    # ── 3. Push tickets to the Jira project ─────────────────────
    effective_project_key = conversation.jira_project_key
    ticket_list = tickets_data.get("tickets", [])

    if ticket_list and effective_project_key and not jira_error:
        try:
            raw_results = await push_tickets_to_jira(
                user_id=user_id,
                db=db,
                tickets=ticket_list,
                project_key=effective_project_key,
                cloud_id=jira_cloud_id,
            )
            jira_tickets_created = [r for r in raw_results if "key" in r]
            failed               = [r for r in raw_results if "error" in r]

            if jira_tickets_created:
                logger.info(
                    "%d Jira ticket(s) created for conversation %s.",
                    len(jira_tickets_created), conversation_id,
                )
            if failed:
                titles    = ", ".join(f.get("title", "?") for f in failed)
                first_err = failed[0].get("error", "unknown error")
                jira_error = (
                    f"{len(failed)} ticket(s) failed to create ({titles}). "
                    f"Jira error: {first_err}"
                )
                logger.warning(
                    "Partial Jira failure for conversation %s: %s",
                    conversation_id, jira_error,
                )
        except JiraServiceError as exc:
            jira_error = str(exc)
            logger.warning(
                "Jira ticket push failed for conversation %s: %s",
                conversation_id, exc,
            )

    # ── 4. Persist tickets to local DB for agent tracking ───────────
    # This must happen after the Jira push so we can map Jira issue keys.
    if tickets_data and tickets_data.get("tickets"):
        store_tickets(
            conversation_id=conversation_id,
            tickets_data=tickets_data,
            jira_results=jira_tickets_created,
            db=db,
        )

        # ── 5. Auto-start dev agents in the background ──────────────
        background_tasks.add_task(run_all_tickets_bg, conversation_id, user_id)
        logger.info(
            "Dev agents queued in background for conversation %s.",
            conversation_id,
        )

    # ── Persist the trigger message + friendly agent confirmation ───
    # The raw LLM reply (result["agent_reply"]) is the JSON dump used to
    # create Jira tickets — we intentionally do NOT store it in the chat
    # thread.  Instead we store a human-readable confirmation so the PM's
    # response is what actually surfaces in the UI.
    db.add(Message(
        conversation_id=conversation_id,
        role="user",
        content=pm_agent.TASKING_ACTION_MESSAGE,
    ))
    db.add(Message(
        conversation_id=conversation_id,
        role="agent",
        content=TASKING_COMPLETE_AGENT_MESSAGE,
    ))

    # ── Transition conversation status ────────────────────────────
    conversation.status = "tasking"
    db.commit()
    db.refresh(conversation)

    # ── Build final message list (includes the two new rows) ──────
    all_messages = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
        .all()
    )

    if jira_error:
        logger.warning(
            "Jira error for conversation %s (user %s): %s",
            conversation_id, user_id, jira_error,
        )

    return TaskingResult(
        conversation=ConversationRead.model_validate(conversation),
        messages=[MessageRead.model_validate(m) for m in all_messages],
        tickets=result.get("tickets"),
        jira_tickets_created=jira_tickets_created,
        jira_error=jira_error,
    )


@router.post("/{conversation_id}/reopen", response_model=ConversationDetail)
def reopen_conversation(conversation_id: int, db: Session = Depends(get_db)):
    """
    Transitions a 'tasking' or 'done' conversation back to 'active' so the user
    can continue chatting with the PM agent to define additional requirements.
    Called when the user clicks "Yes" or "Add more requirements".
    """
    conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conversation.status not in ("tasking", "done"):
        raise HTTPException(status_code=400, detail="Conversation is not in a reopenable state.")

    conversation.status = "active"
    db.commit()
    db.refresh(conversation)
    return _build_detail(conversation, db)


@router.post("/{conversation_id}/decline-tasking", response_model=ConversationDetail)
def decline_tasking(conversation_id: int, db: Session = Depends(get_db)):
    """
    Called when the user clicks "No" after tickets have been generated.
    Stores the PM's closing message and transitions the conversation to 'done'.
    The user can still reopen via the 'Add more requirements' button.
    """
    conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conversation.status != "tasking":
        raise HTTPException(status_code=400, detail="Conversation is not in a declinable state.")

    db.add(Message(
        conversation_id=conversation_id,
        role="agent",
        content=TASKING_DECLINED_AGENT_MESSAGE,
    ))
    conversation.status = "done"
    db.commit()
    db.refresh(conversation)
    return _build_detail(conversation, db)
