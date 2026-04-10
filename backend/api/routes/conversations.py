import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from db.database import get_db
from models.conversation import Conversation
from models.idea import Idea
from models.message import Message
from schemas.conversation import (
    ConversationCreate,
    ConversationDetail,
    ConversationRead,
    TaskingResult,
)
from schemas.message import MessageCreate, MessageRead
from services import pm_agent
from services.auth_service import SECRET_KEY, ALGORITHM

logger = logging.getLogger(__name__)

# Optional bearer: does not raise 401 when the header is absent, so
# unauthenticated callers can still use conversations (Jira is simply skipped).
_optional_bearer = HTTPBearer(auto_error=False)

router = APIRouter(prefix="/conversations", tags=["conversations"])


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
def create_conversation(payload: ConversationCreate, db: Session = Depends(get_db)):
    """
    Creates an idea, a conversation, the user's opening message,
    and the PM agent's first clarifying response — all in one shot.
    """
    # 1. Persist the idea
    idea = Idea(content=payload.content)
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
    db: Session = Depends(get_db),
):
    """
    Appends a user message, calls the PM agent with the full conversation
    history, and returns the updated thread.
    """
    conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conversation.status == "tasking":
        raise HTTPException(status_code=400, detail="Conversation is already in tasking mode")

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
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_optional_bearer),
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
    conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if conversation.status == "tasking":
        raise HTTPException(status_code=400, detail="Conversation is already in tasking mode.")

    # ── Resolve caller identity (optional auth) ───────────────────
    # If an Authorization header is present and valid, we use that user_id
    # to look up the Jira token.  If absent or invalid, Jira is skipped.
    user_id: int | None = None
    if credentials:
        try:
            payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
            user_id = int(payload["sub"])
        except (JWTError, KeyError, ValueError):
            logger.debug("start_tasking: bearer token present but invalid — skipping Jira.")

    # ── Build full conversation history for the LLM ───────────────
    existing_messages = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
        .all()
    )
    llm_history = _build_llm_history(existing_messages)

    # ── Call PM agent (generates tickets + optionally creates in Jira) ──
    result = await pm_agent.run_tasking(
        history=llm_history,
        user_id=user_id,
        db=db,
    )

    # ── Persist the trigger message + agent reply ─────────────────
    db.add(Message(
        conversation_id=conversation_id,
        role="user",
        content=pm_agent.TASKING_ACTION_MESSAGE,
    ))
    db.add(Message(
        conversation_id=conversation_id,
        role="agent",
        content=result["agent_reply"],
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

    if result.get("jira_error"):
        logger.warning(
            "Jira push failed for conversation %s (user %s): %s",
            conversation_id, user_id, result["jira_error"],
        )

    return TaskingResult(
        conversation=ConversationRead.model_validate(conversation),
        messages=[MessageRead.model_validate(m) for m in all_messages],
        tickets=result.get("tickets"),
        jira_tickets_created=result.get("jira_tickets_created", []),
        jira_error=result.get("jira_error"),
    )
