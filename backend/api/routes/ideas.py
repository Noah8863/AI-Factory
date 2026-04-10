from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from db.database import get_db
from models.idea import Idea
from models.conversation import Conversation
from models.message import Message
from schemas.idea import IdeaCreate, IdeaRead
from schemas.conversation import ConversationDetail, ConversationRead
from schemas.message import MessageRead

router = APIRouter(prefix="/ideas", tags=["ideas"])


@router.post("", response_model=IdeaRead, status_code=201)
def create_idea(payload: IdeaCreate, db: Session = Depends(get_db)):
    idea = Idea(content=payload.content)
    db.add(idea)
    db.commit()
    db.refresh(idea)
    return idea


@router.get("", response_model=list[IdeaRead])
def list_ideas(db: Session = Depends(get_db)):
    return db.query(Idea).order_by(Idea.created_at.desc()).all()


@router.get("/{idea_id}", response_model=IdeaRead)
def get_idea(idea_id: int, db: Session = Depends(get_db)):
    idea = db.query(Idea).filter(Idea.id == idea_id).first()
    if not idea:
        raise HTTPException(status_code=404, detail="Idea not found")
    return idea


@router.get("/{idea_id}/conversation", response_model=ConversationDetail)
def get_idea_conversation(idea_id: int, db: Session = Depends(get_db)):
    """Return the most recent conversation (with full message history) for an idea."""
    idea = db.query(Idea).filter(Idea.id == idea_id).first()
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
def delete_idea(idea_id: int, db: Session = Depends(get_db)):
    """Delete an idea and all its conversations and messages."""
    idea = db.query(Idea).filter(Idea.id == idea_id).first()
    if not idea:
        raise HTTPException(status_code=404, detail="Idea not found")

    # Delete messages → conversations → idea (respect FK order)
    conv_ids = [
        c.id for c in db.query(Conversation.id).filter(Conversation.idea_id == idea_id).all()
    ]
    if conv_ids:
        db.query(Message).filter(Message.conversation_id.in_(conv_ids)).delete(synchronize_session=False)
        db.query(Conversation).filter(Conversation.idea_id == idea_id).delete(synchronize_session=False)

    db.delete(idea)
    db.commit()
