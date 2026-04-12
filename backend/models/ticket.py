from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text

from db.database import Base


class Ticket(Base):
    """
    Stores every PM-generated ticket locally for agent tracking.

    status lifecycle:
      pending → in_progress → done
                           → failed   (error_msg populated)
    """

    __tablename__ = "tickets"

    id              = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False, index=True)

    # PM-assigned identifiers
    ticket_id       = Column(String(16),  nullable=False)   # "BE-1", "FE-3"
    jira_issue_key  = Column(String(32),  nullable=True)    # "MYAPP-5" (from Jira API response)

    # Routing & ordering
    type            = Column(String(16),  nullable=False)   # "backend" | "frontend"
    phase           = Column(String(32),  nullable=True)    # Foundation|Core|Integration|Polish
    sequence        = Column(Integer,     nullable=True)
    depends_on      = Column(JSON,        default=list)     # ["BE-1", "FE-2"]
    priority        = Column(String(16),  nullable=True)    # High|Medium|Low

    # Content
    title           = Column(String(512), nullable=False)
    description     = Column(Text,        nullable=False, default="")
    story_points    = Column(Integer,     nullable=True)
    labels          = Column(JSON,        default=list)

    # Execution state
    status          = Column(String(32),  nullable=False, default="pending")
    error_msg       = Column(Text,        nullable=True)
    agent_output    = Column(Text,        nullable=True)    # raw JSON from agent

    created_at      = Column(DateTime, default=datetime.utcnow)
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
