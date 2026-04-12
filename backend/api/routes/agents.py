"""
api/routes/agents.py
────────────────────
Routes for triggering and monitoring AI developer agent work.

  POST /agents/{conversation_id}/run
      Queues all pending tickets for execution.  Returns immediately; agents
      run in a background task.  Poll /tickets for progress.

  GET  /agents/{conversation_id}/tickets
      Returns the current status of every ticket in the conversation.

  POST /agents/{conversation_id}/tickets/{ticket_db_id}/retry
      Resets a single failed ticket to 'pending' and re-queues execution.
"""

import logging
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from db.database import get_db
from models.conversation import Conversation
from models.ticket import Ticket
from schemas.ticket import AgentRunResponse, TicketRead
from services.agent_runner import get_runnable_tickets, run_all_tickets_bg
from services.auth_service import get_current_user
from models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents", tags=["agents"])


# ── Helper ────────────────────────────────────────────────────────────────────

def _ticket_counts(tickets: list[Ticket]) -> dict:
    done    = sum(1 for t in tickets if t.status in ("done", "cancelled"))
    failed  = sum(1 for t in tickets if t.status == "failed")
    pending = sum(1 for t in tickets if t.status in ("pending", "in_progress"))
    return {"done": done, "failed": failed, "still_pending": pending}


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/{conversation_id}/run", response_model=AgentRunResponse)
async def run_agents(
    conversation_id:  int,
    background_tasks: BackgroundTasks,
    current_user:     User = Depends(get_current_user),
    db:               Session = Depends(get_db),
):
    """
    Kick off agent execution for all pending/failed tickets in the conversation.

    Returns immediately — agents run in the background.
    Poll GET /agents/{conversation_id}/tickets to track progress.
    """
    conversation = db.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found.")

    tickets = (
        db.query(Ticket)
        .filter(Ticket.conversation_id == conversation_id)
        .order_by(Ticket.sequence.asc().nullslast())
        .all()
    )
    if not tickets:
        raise HTTPException(
            status_code=404,
            detail="No tickets found for this conversation. Run Start Building first.",
        )

    runnable = get_runnable_tickets(conversation_id, None, db)
    if not runnable:
        counts = _ticket_counts(tickets)
        if counts["still_pending"] == 0:
            raise HTTPException(
                status_code=400,
                detail="All tickets are already done or failed.",
            )
        raise HTTPException(
            status_code=400,
            detail=(
                "No tickets are ready to run right now — their dependencies "
                "may not be satisfied yet."
            ),
        )

    # Guard: if any ticket is already in_progress, a runner is already active.
    # Queuing a second one would cause duplicate commits for the same ticket.
    already_running = (
        db.query(Ticket)
        .filter(Ticket.conversation_id == conversation_id, Ticket.status == "in_progress")
        .first()
    )
    if already_running:
        logger.info(
            "Skipping duplicate agent launch for conversation %s — already running.",
            conversation_id,
        )
        counts = _ticket_counts(tickets)
        return AgentRunResponse(
            conversation_id=conversation_id,
            tickets=[TicketRead.model_validate(t) for t in tickets],
            **counts,
        )

    background_tasks.add_task(run_all_tickets_bg, conversation_id, current_user.id)
    logger.info(
        "Agent run queued for conversation %s by user %s (%d runnable now).",
        conversation_id, current_user.id, len(runnable),
    )

    counts = _ticket_counts(tickets)
    return AgentRunResponse(
        conversation_id=conversation_id,
        tickets=[TicketRead.model_validate(t) for t in tickets],
        **counts,
    )


@router.get("/{conversation_id}/tickets", response_model=AgentRunResponse)
def get_ticket_status(
    conversation_id: int,
    db:              Session = Depends(get_db),
):
    """Return current ticket statuses for a conversation (for polling)."""
    tickets = (
        db.query(Ticket)
        .filter(Ticket.conversation_id == conversation_id)
        .order_by(Ticket.sequence.asc().nullslast())
        .all()
    )
    counts = _ticket_counts(tickets)
    return AgentRunResponse(
        conversation_id=conversation_id,
        tickets=[TicketRead.model_validate(t) for t in tickets],
        **counts,
    )


@router.post("/{conversation_id}/cancel", status_code=200)
def cancel_agents(
    conversation_id: int,
    current_user:    User = Depends(get_current_user),
    db:              Session = Depends(get_db),
):
    """
    Signal any running background agent task to stop after the current ticket.

    Sets conversation.cancelled = True and marks all pending tickets as
    'cancelled' so the pipeline loop exits cleanly on its next wave check.
    Any ticket currently being worked on by the LLM will finish its API call
    but will not write results back to the DB.
    """
    conversation = db.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found.")

    conversation.cancelled  = True
    conversation.updated_at = datetime.utcnow()

    # Mark every pending ticket as cancelled so the UI clears immediately
    pending_tickets = (
        db.query(Ticket)
        .filter(
            Ticket.conversation_id == conversation_id,
            Ticket.status.in_(["pending"]),
        )
        .all()
    )
    for t in pending_tickets:
        t.status     = "cancelled"
        t.updated_at = datetime.utcnow()

    db.commit()

    logger.info(
        "Conversation %s cancelled by user %s. %d pending ticket(s) marked cancelled.",
        conversation_id, current_user.id, len(pending_tickets),
    )
    return {"cancelled": True, "tickets_cancelled": len(pending_tickets)}


@router.post("/{conversation_id}/tickets/{ticket_db_id}/retry", response_model=AgentRunResponse)
async def retry_ticket(
    conversation_id:  int,
    ticket_db_id:     int,
    background_tasks: BackgroundTasks,
    current_user:     User = Depends(get_current_user),
    db:               Session = Depends(get_db),
):
    """
    Reset a failed ticket to 'pending' and re-queue agent execution.
    All other runnable tickets will also be picked up in the same background run.
    """
    ticket = db.get(Ticket, ticket_db_id)
    if not ticket or ticket.conversation_id != conversation_id:
        raise HTTPException(status_code=404, detail="Ticket not found.")
    if ticket.status != "failed":
        raise HTTPException(status_code=400, detail="Only failed tickets can be retried.")

    ticket.status    = "pending"
    ticket.error_msg = None
    db.commit()

    background_tasks.add_task(run_all_tickets_bg, conversation_id, current_user.id)

    tickets = (
        db.query(Ticket)
        .filter(Ticket.conversation_id == conversation_id)
        .order_by(Ticket.sequence.asc().nullslast())
        .all()
    )
    counts = _ticket_counts(tickets)
    return AgentRunResponse(
        conversation_id=conversation_id,
        tickets=[TicketRead.model_validate(t) for t in tickets],
        **counts,
    )
