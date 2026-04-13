from datetime import datetime
from sqlalchemy import Boolean, Column, Integer, JSON, String, DateTime, ForeignKey
from db.database import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    idea_id = Column(Integer, ForeignKey("ideas.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    # Statuses: active | ready_to_task | tasking | done
    status = Column(String(32), default="active", nullable=False)
    # Set to True to signal any running background agent task to stop
    cancelled = Column(Boolean, default=False, nullable=False)
    # Project type tags set by the PM agent at ticket-generation time.
    # Possible values: "has_frontend", "has_backend", "is_script",
    #                  "is_mobile_app", "is_devops_program"
    project_tags = Column(JSON, default=list, nullable=True)
    # GitHub repo created when the user first clicks "Start Building"
    github_repo_name = Column(String(255), nullable=True)
    github_repo_url  = Column(String(512), nullable=True)
    # Jira project auto-created on first "Start Building"
    jira_project_key = Column(String(32),  nullable=True)
    jira_project_url = Column(String(512), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
