from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey

from db.database import Base


class JiraToken(Base):
    __tablename__ = "jira_tokens"

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False, index=True)
    access_token  = Column(String, nullable=False)
    refresh_token = Column(String, nullable=True)   # Jira Cloud OAuth2 returns one; store null until available
    expires_at    = Column(DateTime, nullable=False) # UTC datetime when access_token expires
    created_at    = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
