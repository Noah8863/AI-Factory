from datetime import datetime
from sqlalchemy import Column, Integer, Text, String, DateTime
from db.database import Base


class Idea(Base):
    __tablename__ = "ideas"

    id = Column(Integer, primary_key=True, index=True)
    content = Column(Text, nullable=False)
    status = Column(String(32), default="pending", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
