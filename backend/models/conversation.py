from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from db.database import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    idea_id = Column(Integer, ForeignKey("ideas.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    # Statuses: active | ready_to_task | tasking | done
    status = Column(String(32), default="active", nullable=False)
    # GitHub repo created when the user first clicks "Start Building"
    github_repo_name = Column(String(255), nullable=True)
    github_repo_url  = Column(String(512), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
