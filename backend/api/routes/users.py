from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db.database import get_db
from models.user import User
from models.user_settings import UserSettings
from models.idea import Idea
from models.conversation import Conversation
from models.message import Message
from schemas.user_settings import UserSettingsRead, UserSettingsUpdate
from schemas.idea import IdeaRead
from schemas.conversation import ConversationRead
from services.auth_service import get_current_user

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me/settings", response_model=UserSettingsRead)
def get_settings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    settings = db.query(UserSettings).filter(UserSettings.user_id == current_user.id).first()
    if not settings:
        raise HTTPException(status_code=404, detail="Settings not found")
    return UserSettingsRead.model_validate(settings)


@router.patch("/me/settings", response_model=UserSettingsRead)
def update_settings(
    payload: UserSettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    settings = db.query(UserSettings).filter(UserSettings.user_id == current_user.id).first()
    if not settings:
        raise HTTPException(status_code=404, detail="Settings not found")

    if payload.theme is not None:
        settings.theme = payload.theme
    if payload.notifications_enabled is not None:
        settings.notifications_enabled = payload.notifications_enabled

    db.commit()
    db.refresh(settings)
    return UserSettingsRead.model_validate(settings)


@router.get("/me/ideas", response_model=list[IdeaRead])
def get_my_ideas(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (
        db.query(Idea)
        .filter(Idea.user_id == current_user.id)
        .order_by(Idea.created_at.desc())
        .all()
    )


@router.get("/me/conversations", response_model=list[ConversationRead])
def get_my_conversations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (
        db.query(Conversation)
        .filter(Conversation.user_id == current_user.id)
        .order_by(Conversation.created_at.desc())
        .all()
    )
