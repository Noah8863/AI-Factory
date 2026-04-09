from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from db.database import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    idea_id = Column(Integer, ForeignKey("ideas.id"), nullable=False)
    # Statuses: active | ready_to_task | tasking
    status = Column(String(32), default="active", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
