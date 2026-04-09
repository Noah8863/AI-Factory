from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db.database import get_db
from models.idea import Idea
from models.conversation import Conversation
from models.message import Message
from schemas.conversation import ConversationCreate, ConversationRead, ConversationDetail
from schemas.message import MessageCreate, MessageRead
from services import pm_agent

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


@router.post("/{conversation_id}/start-tasking", response_model=ConversationRead)
def start_tasking(conversation_id: int, db: Session = Depends(get_db)):
    """
    Transitions the conversation to 'tasking'. The actual task-creation
    pipeline will hook in here later.
    """
    conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conversation.status = "tasking"
    db.commit()
    db.refresh(conversation)
    return ConversationRead.model_validate(conversation)
