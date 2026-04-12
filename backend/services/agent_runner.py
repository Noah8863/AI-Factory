"""
services/agent_runner.py
────────────────────────
Orchestrates AI developer agents against the stored ticket queue.

Public API
──────────
  store_tickets(conversation_id, tickets_data, jira_results, db)
      Persists PM-generated tickets to the local DB, mapping Jira issue keys.
      Called by conversations.start_tasking() after Jira push.

  get_runnable_tickets(conversation_id, ticket_type, db)
      Returns tickets that are pending AND whose dependencies are all done.

  run_ticket(ticket_db_id, user_id, conversation, db)  [async]
      Executes a single ticket with the right agent service.
      Marks in_progress → done/failed. Writes generated files to GitHub.

  run_all_tickets(conversation_id, user_id, db)  [async]
      Top-level pipeline: repeats rounds of runnable tickets until nothing
      is left or a safety limit is hit.

  run_all_tickets_bg(conversation_id, user_id)  [async]
      BackgroundTask wrapper — creates its own DB session.
"""

import asyncio
import json
import logging
from datetime import datetime

from sqlalchemy.orm import Session

from db.database import SessionLocal
from models.conversation import Conversation
from models.ticket import Ticket

logger = logging.getLogger(__name__)


# ── Ticket storage ────────────────────────────────────────────────────────────

def store_tickets(
    conversation_id: int,
    tickets_data: dict,
    jira_results: list[dict],
    db: Session,
) -> list[Ticket]:
    """
    Persist PM-generated tickets to the local DB.

    jira_results is the list returned by push_tickets_to_jira — each entry
    has at minimum {"title": str, "key": str} on success or {"error": ...}
    on failure.  We map title → Jira key so we can transition issue status
    later.
    """
    ticket_list = tickets_data.get("tickets", [])
    if not ticket_list:
        logger.info("store_tickets: no tickets in payload for conversation %s.", conversation_id)
        return []

    # Build title → Jira issue key lookup from successful results
    title_to_jira_key: dict[str, str] = {
        r["title"]: r["key"]
        for r in jira_results
        if "key" in r and "title" in r
    }

    rows: list[Ticket] = []
    for t in ticket_list:
        row = Ticket(
            conversation_id=conversation_id,
            ticket_id=t.get("id", ""),
            jira_issue_key=title_to_jira_key.get(t.get("title", "")),
            type=t.get("type", "backend"),
            phase=t.get("phase"),
            sequence=t.get("sequence"),
            depends_on=t.get("dependsOn") or [],
            priority=t.get("priority"),
            title=t.get("title", ""),
            description=t.get("description", ""),
            story_points=t.get("storyPoints"),
            labels=t.get("labels") or [],
            status="pending",
        )
        db.add(row)
        rows.append(row)

    db.commit()
    for r in rows:
        db.refresh(r)

    logger.info(
        "Stored %d ticket(s) for conversation %s (%d mapped to Jira keys).",
        len(rows), conversation_id, len(title_to_jira_key),
    )
    return rows


# ── Dependency resolution ─────────────────────────────────────────────────────

def _deps_satisfied(ticket: Ticket, all_tickets: list[Ticket]) -> bool:
    """
    True if every ticket ID listed in ticket.depends_on is already 'done'.
    Tickets with no dependencies can always start immediately.
    """
    if not ticket.depends_on:
        return True
    done_ids = {t.ticket_id for t in all_tickets if t.status == "done"}
    return all(dep in done_ids for dep in ticket.depends_on)


def get_runnable_tickets(
    conversation_id: int,
    ticket_type: str | None,
    db: Session,
) -> list[Ticket]:
    """
    Return pending tickets whose dependencies are all satisfied, ordered by
    sequence (nulls last).  If ticket_type is given ('backend' | 'frontend'),
    only tickets of that type are returned.
    """
    q = (
        db.query(Ticket)
        .filter(
            Ticket.conversation_id == conversation_id,
            Ticket.status == "pending",
        )
    )
    if ticket_type:
        q = q.filter(Ticket.type == ticket_type)

    pending = q.order_by(Ticket.sequence.asc().nullslast()).all()

    all_conv_tickets = (
        db.query(Ticket)
        .filter(Ticket.conversation_id == conversation_id)
        .all()
    )
    return [t for t in pending if _deps_satisfied(t, all_conv_tickets)]


# ── Single ticket execution ───────────────────────────────────────────────────

async def run_ticket(
    ticket_db_id: int,
    user_id: int,
    conversation: Conversation,
    db: Session,
) -> bool:
    """
    Execute a single ticket by dispatching to the right agent service.
    Returns True on success, False on failure.
    """
    # Import here to avoid circular imports at module load time
    from services import backend_agent as be_svc
    from services import frontend_agent as fe_svc
    from services.jira_service import transition_jira_issue

    ticket = db.get(Ticket, ticket_db_id)
    if not ticket:
        logger.error("run_ticket: ticket DB id %s not found.", ticket_db_id)
        return False

    logger.info(
        "Running ticket %s (%s) seq=%s — %s",
        ticket.ticket_id, ticket.type, ticket.sequence, ticket.title,
    )

    from models.jira_token import JiraToken

    # ── Mark in-progress ──────────────────────────────────────────────────────
    ticket.status     = "in_progress"
    ticket.updated_at = datetime.utcnow()
    db.commit()

    # Resolve Jira cloud_id once — used for status transitions (best-effort)
    cloud_id: str | None = None
    token_row = db.query(JiraToken).filter_by(user_id=user_id).first()
    if token_row:
        cloud_id = token_row.jira_cloud_id

    # Transition Jira issue to "In Progress" (best-effort — non-fatal)
    if ticket.jira_issue_key and cloud_id:
        await transition_jira_issue(
            user_id=user_id,
            db=db,
            cloud_id=cloud_id,
            issue_key=ticket.jira_issue_key,
            target_status="In Progress",
        )

    repo_name = conversation.github_repo_name or ""

    # Build a rich prompt from ticket metadata
    deps_str = ", ".join(ticket.depends_on) if ticket.depends_on else "none"
    ticket_prompt = (
        f"# Ticket {ticket.ticket_id}: {ticket.title}\n\n"
        f"**Phase:** {ticket.phase or 'N/A'} | "
        f"**Priority:** {ticket.priority or 'N/A'} | "
        f"**Sequence:** {ticket.sequence or 'N/A'} | "
        f"**Depends on:** {deps_str}\n\n"
        f"## Acceptance Criteria\n\n{ticket.description}\n\n"
        f"## Target Repository\n`{repo_name}`\n"
    )

    try:
        if ticket.type == "backend":
            result = await be_svc.run_backend_task(
                ticket=ticket,
                ticket_prompt=ticket_prompt,
                repo_name=repo_name,
            )
        else:
            result = await fe_svc.run_frontend_task(
                ticket=ticket,
                ticket_prompt=ticket_prompt,
                repo_name=repo_name,
            )

        ticket.agent_output = json.dumps(result)
        ticket.status       = "done"
        ticket.updated_at   = datetime.utcnow()
        db.commit()

        logger.info(
            "Ticket %s done. Files written: %d.",
            ticket.ticket_id,
            result.get("files_written", 0),
        )

        # Transition Jira issue to Done (best-effort)
        if ticket.jira_issue_key and cloud_id:
            await transition_jira_issue(
                user_id=user_id,
                db=db,
                cloud_id=cloud_id,
                issue_key=ticket.jira_issue_key,
                target_status="Done",
            )

        return True

    except Exception as exc:
        logger.exception("Ticket %s failed: %s", ticket.ticket_id, exc)
        ticket.status     = "failed"
        ticket.error_msg  = str(exc)
        ticket.updated_at = datetime.utcnow()
        db.commit()
        return False


# ── Full pipeline ─────────────────────────────────────────────────────────────

async def run_all_tickets(
    conversation_id: int,
    user_id: int,
    db: Session,
) -> dict:
    """
    Run all pending tickets for a conversation in dependency order.

    Each round finds all tickets whose deps are satisfied and dispatches them
    concurrently (same sequence level = safe to parallelise).  Continues until
    no more runnable tickets exist or a safety round-limit is hit.

    Returns:
        {"done": int, "failed": int, "still_pending": int}
    """
    conversation = db.get(Conversation, conversation_id)
    if not conversation:
        logger.error("run_all_tickets: conversation %s not found.", conversation_id)
        return {"error": "Conversation not found"}

    done_count  = 0
    fail_count  = 0
    max_rounds  = 50   # prevents infinite loops if deps are cyclic

    for _ in range(max_rounds):
        runnable = get_runnable_tickets(conversation_id, None, db)
        if not runnable:
            break

        # All tickets at the lowest sequence share a "ready" wave and can
        # run concurrently.  Tickets without a sequence are treated as last.
        current_seq = runnable[0].sequence
        batch = [
            t for t in runnable
            if t.sequence == current_seq
        ]

        logger.info(
            "Agent wave: seq=%s — %d ticket(s): %s",
            current_seq,
            len(batch),
            [t.ticket_id for t in batch],
        )

        results = await asyncio.gather(
            *[run_ticket(t.id, user_id, conversation, db) for t in batch],
            return_exceptions=True,
        )
        for ok in results:
            if ok is True:
                done_count += 1
            else:
                fail_count += 1

    all_tickets   = db.query(Ticket).filter(Ticket.conversation_id == conversation_id).all()
    still_pending = sum(1 for t in all_tickets if t.status in ("pending", "in_progress"))

    logger.info(
        "run_all_tickets for conversation %s complete — done=%d failed=%d still_pending=%d",
        conversation_id, done_count, fail_count, still_pending,
    )
    return {
        "done":          done_count,
        "failed":        fail_count,
        "still_pending": still_pending,
    }


# ── Background task wrapper ───────────────────────────────────────────────────

async def run_all_tickets_bg(conversation_id: int, user_id: int) -> None:
    """
    Creates its own DB session so it can safely run as a FastAPI BackgroundTask
    without sharing the request-scoped session.
    """
    db = SessionLocal()
    try:
        await run_all_tickets(conversation_id, user_id, db)
    except Exception:
        logger.exception(
            "Background agent run failed for conversation %s.", conversation_id
        )
    finally:
        db.close()
