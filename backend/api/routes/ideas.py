from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from db.database import get_db
from models.idea import Idea
from models.conversation import Conversation
from models.message import Message
from models.ticket import Ticket
from models.user import User
from schemas.idea import IdeaCreate, IdeaRead
from schemas.conversation import ConversationDetail, ConversationRead
from schemas.message import MessageRead
from schemas.ticket import AgentRunResponse, TicketRead
from services.auth_service import get_current_user

router = APIRouter(prefix="/ideas", tags=["ideas"])


@router.post("", response_model=IdeaRead, status_code=201)
def create_idea(
    payload: IdeaCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    idea = Idea(content=payload.content, user_id=current_user.id)
    db.add(idea)
    db.commit()
    db.refresh(idea)
    return idea


@router.get("", response_model=list[IdeaRead])
def list_ideas(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (
        db.query(Idea)
        .filter(Idea.user_id == current_user.id)
        .order_by(Idea.created_at.desc())
        .all()
    )


@router.get("/{idea_id}", response_model=IdeaRead)
def get_idea(
    idea_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    idea = db.query(Idea).filter(Idea.id == idea_id, Idea.user_id == current_user.id).first()
    if not idea:
        raise HTTPException(status_code=404, detail="Idea not found")
    return idea


@router.get("/{idea_id}/conversation", response_model=ConversationDetail)
def get_idea_conversation(
    idea_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the most recent conversation (with full message history) for an idea."""
    idea = db.query(Idea).filter(Idea.id == idea_id, Idea.user_id == current_user.id).first()
    if not idea:
        raise HTTPException(status_code=404, detail="Idea not found")

    conversation = (
        db.query(Conversation)
        .filter(Conversation.idea_id == idea_id)
        .order_by(Conversation.created_at.desc())
        .first()
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="No conversation found for this idea")

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


@router.delete("/{idea_id}", status_code=204)
def delete_idea(
    idea_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete an idea and all its conversations and messages."""
    idea = db.query(Idea).filter(Idea.id == idea_id, Idea.user_id == current_user.id).first()
    if not idea:
        raise HTTPException(status_code=404, detail="Idea not found")

    # Signal any running background agent tasks to stop before we delete rows.
    # The agent pipeline checks conversation.cancelled at the start of each wave
    # and before writing results back, so this prevents writes to deleted rows.
    conv_ids = [
        c.id for c in db.query(Conversation.id).filter(Conversation.idea_id == idea_id).all()
    ]
    if conv_ids:
        db.query(Conversation).filter(Conversation.idea_id == idea_id).update(
            {"cancelled": True, "updated_at": datetime.utcnow()},
            synchronize_session=False,
        )
        db.commit()

        # Delete tickets → messages → conversations → idea (respect FK order)
        db.query(Ticket).filter(Ticket.conversation_id.in_(conv_ids)).delete(synchronize_session=False)
        db.query(Message).filter(Message.conversation_id.in_(conv_ids)).delete(synchronize_session=False)
        db.query(Conversation).filter(Conversation.idea_id == idea_id).delete(synchronize_session=False)

    db.delete(idea)
    db.commit()


@router.get("/{idea_id}/tickets", response_model=AgentRunResponse)
def get_idea_tickets(
    idea_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return ticket statuses for the most recent conversation of an idea."""
    idea = db.query(Idea).filter(Idea.id == idea_id, Idea.user_id == current_user.id).first()
    if not idea:
        raise HTTPException(status_code=404, detail="Idea not found")

    conversation = (
        db.query(Conversation)
        .filter(Conversation.idea_id == idea_id)
        .order_by(Conversation.created_at.desc())
        .first()
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="No conversation found for this idea")

    tickets = (
        db.query(Ticket)
        .filter(Ticket.conversation_id == conversation.id)
        .order_by(Ticket.sequence.asc().nullslast())
        .all()
    )
    done = sum(1 for t in tickets if t.status == "done")
    failed = sum(1 for t in tickets if t.status == "failed")
    still_pending = sum(1 for t in tickets if t.status in ("pending", "in_progress"))
    return AgentRunResponse(
        conversation_id=conversation.id,
        tickets=[TicketRead.model_validate(t) for t in tickets],
        done=done,
        failed=failed,
        still_pending=still_pending,
    )
