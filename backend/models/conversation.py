from datetime import datetime
from sqlalchemy import Boolean, Column, Integer, JSON, String, Text, DateTime, ForeignKey
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
    # Shared architectural blueprint generated before agents run.
    # Injected into every developer agent prompt so both BE and FE share the same
    # mental model of pages, endpoints, data models, and integration contract.
    project_blueprint = Column(Text, nullable=True)
    # Project type tags set by the PM agent at ticket-generation time.
    # Stored as an object keyed by the canonical tag names.
    project_tags = Column(JSON, default=dict, nullable=True)
    # Product-type switch negotiation state.
    asked_user_change_product_type = Column(Boolean, default=False, nullable=False)
    pending_project_type = Column(String(64), nullable=True)
    # GitHub repo created when the user first clicks "Start Building"
    github_repo_name = Column(String(255), nullable=True)
    github_repo_url  = Column(String(512), nullable=True)
    # Deployment lifecycle for frontend/full-stack projects.
    deployment_status      = Column(String(32), default="not_deployed", nullable=False)
    deployment_live_url    = Column(String(512), nullable=True)
    deployment_error       = Column(String(1024), nullable=True)
    # Railway backend URL stored after successful Railway deployment.
    # Used as proxy target in netlify.toml on first deploy and as fallback on re-deploys.
    backend_service_url    = Column(String(512), nullable=True)
    # Jira project auto-created on first "Start Building"
    jira_project_key = Column(String(32),  nullable=True)
    jira_project_url = Column(String(512), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
