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
import traceback
from datetime import datetime

from sqlalchemy.orm import Session

from db.database import SessionLocal
from models.conversation import Conversation
from models.ticket import Ticket

logger = logging.getLogger(__name__)

_AUTO_SPLIT_MAX_ATTEMPTS = 2
_AUTO_SPLIT_MAX_PARTS = 3


def _build_error_msg(exc: Exception, stage: str = "unknown") -> str:
    """
    Build a structured, human-readable error message that preserves:
    - The exception class name
    - The stage of execution that failed
    - The full exception message
    - The last 5 frames of the traceback
    """
    tb_lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
    # Keep only the last 5 frames to avoid huge blobs
    short_tb = "".join(tb_lines[-6:])  # -6 because the last entry is the exception line itself
    return (
        f"[{type(exc).__name__}] Stage: {stage}\n"
        f"{exc}\n"
        f"--- traceback (last 5 frames) ---\n{short_tb}"
    )


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

    # Collect existing ticket_ids for this conversation to prevent duplicate rows
    # (defense-in-depth: the "tasking" early-lock in start_tasking normally
    # prevents concurrent calls, but this guard makes store_tickets idempotent).
    existing_ids: set[str] = {
        t.ticket_id
        for t in db.query(Ticket.ticket_id)
        .filter(Ticket.conversation_id == conversation_id)
        .all()
    }

    rows: list[Ticket] = []
    for t in ticket_list:
        tid = t.get("id", "")
        if tid and tid in existing_ids:
            logger.warning(
                "store_tickets: skipping duplicate ticket %r for conversation %s.",
                tid, conversation_id,
            )
            continue
        row = Ticket(
            conversation_id=conversation_id,
            ticket_id=tid,
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


def _dedupe_keep_order(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _is_max_token_failure(ticket: Ticket) -> bool:
    msg = (ticket.error_msg or "").lower()
    return "max_tokens" in msg or ("truncated" in msg and "token" in msg)


def _split_attempt_from_labels(labels: list[str] | None) -> int:
    attempts = 0
    for label in labels or []:
        if not isinstance(label, str):
            continue
        if not label.startswith("auto_split_attempt:"):
            continue
        _, _, value = label.partition(":")
        try:
            attempts = max(attempts, int(value))
        except ValueError:
            continue
    return attempts


def _fallback_split_parts(ticket: Ticket) -> list[dict]:
    return [
        {
            "title": f"{ticket.title} - Part 1 (Core setup)",
            "description": (
                "Implement the core structure and foundational pieces required by this ticket. "
                "Keep scope focused on setup, contracts, and essential scaffolding."
            ),
            "priority": ticket.priority or "Medium",
            "phase": ticket.phase or "Core",
        },
        {
            "title": f"{ticket.title} - Part 2 (Completion)",
            "description": (
                "Build on Part 1 and complete the remaining acceptance criteria. "
                "Focus on finishing feature behavior with minimal, production-intent code."
            ),
            "priority": ticket.priority or "Medium",
            "phase": ticket.phase or "Core",
        },
    ]


def _next_split_ticket_id(
    base_ticket_id: str,
    attempt: int,
    part_index: int,
    existing_ids: set[str],
) -> str:
    suffix = part_index
    while True:
        candidate = f"{base_ticket_id}-S{attempt}-{suffix}"
        if candidate not in existing_ids:
            return candidate
        suffix += 1


async def _auto_split_failed_ticket(
    conversation_id: int,
    ticket: Ticket,
    user_id: int,
    conversation: Conversation,
    db: Session,
) -> bool:
    """
    Self-heal path for oversized tickets:
    - Detect max-token failure
    - Split failed ticket into smaller sequential tickets
    - Rewire downstream dependencies from parent -> final split child
    """
    if ticket.status != "failed" or not _is_max_token_failure(ticket):
        return False

    current_attempt = _split_attempt_from_labels(ticket.labels)
    next_attempt = current_attempt + 1
    if next_attempt > _AUTO_SPLIT_MAX_ATTEMPTS:
        logger.warning(
            "Auto-split limit reached for ticket %s (attempts=%d).",
            ticket.ticket_id, current_attempt,
        )
        return False

    from services import pm_agent as pm_svc

    split_request = {
        "id": ticket.ticket_id,
        "type": ticket.type,
        "title": ticket.title,
        "description": ticket.description,
        "priority": ticket.priority,
        "phase": ticket.phase,
        "sequence": ticket.sequence,
        "dependsOn": ticket.depends_on or [],
        "labels": ticket.labels or [],
    }

    split_parts: list[dict] = []
    try:
        split_parts = await asyncio.to_thread(
            pm_svc.split_ticket_for_recovery,
            split_request,
            _AUTO_SPLIT_MAX_PARTS,
        )
    except Exception as exc:
        logger.warning(
            "Auto-split planner failed for ticket %s: %s", ticket.ticket_id, exc,
        )

    if not split_parts:
        split_parts = _fallback_split_parts(ticket)

    existing_ids = {
        tid for (tid,) in db.query(Ticket.ticket_id)
        .filter(Ticket.conversation_id == conversation_id)
        .all()
    }

    now = datetime.utcnow()
    base_sequence = ticket.sequence or 1
    base_labels = list(ticket.labels or [])
    child_labels = _dedupe_keep_order(
        base_labels + [
            "auto_split_child",
            f"auto_split_parent:{ticket.ticket_id}",
            f"auto_split_attempt:{next_attempt}",
        ]
    )

    created_children: list[Ticket] = []
    previous_child_id: str | None = None
    total_parts = len(split_parts)
    sp_per_child = None
    if isinstance(ticket.story_points, int) and ticket.story_points > 0:
        sp_per_child = max(1, round(ticket.story_points / max(total_parts, 1)))

    for idx, part in enumerate(split_parts, start=1):
        child_ticket_id = _next_split_ticket_id(
            ticket.ticket_id,
            next_attempt,
            idx,
            existing_ids,
        )
        existing_ids.add(child_ticket_id)

        if previous_child_id is None:
            child_depends = list(ticket.depends_on or [])
        else:
            child_depends = [previous_child_id]

        child = Ticket(
            conversation_id=conversation_id,
            ticket_id=child_ticket_id,
            jira_issue_key=None,
            type=ticket.type,
            phase=part.get("phase") or ticket.phase,
            sequence=base_sequence + (idx - 1),
            depends_on=child_depends,
            priority=part.get("priority") or ticket.priority,
            title=part.get("title") or f"{ticket.title} - Part {idx}",
            description=part.get("description") or ticket.description,
            story_points=sp_per_child,
            labels=list(child_labels),
            status="pending",
            created_at=now,
            updated_at=now,
        )
        db.add(child)
        created_children.append(child)
        previous_child_id = child_ticket_id

    # Parent ticket is superseded by the split children.
    final_child_id = created_children[-1].ticket_id
    parent_labels = _dedupe_keep_order(
        base_labels + [
            "auto_split_parent_resolved",
            f"auto_split_attempt:{next_attempt}",
        ]
    )
    ticket.labels = parent_labels
    ticket.status = "done"
    ticket.updated_at = now
    split_note = (
        "\n[AUTO_SPLIT] This ticket exceeded model token limits and was automatically "
        f"split into {', '.join(c.ticket_id for c in created_children)}. "
        f"Downstream dependencies were rewired to {final_child_id}."
    )
    ticket.error_msg = (ticket.error_msg or "") + split_note
    ticket.agent_output = json.dumps(
        {
            "auto_split": True,
            "attempt": next_attempt,
            "children": [c.ticket_id for c in created_children],
            "replacement_dependency": final_child_id,
        }
    )

    # Rewrite downstream dependencies from parent ticket ID to last split child.
    final_child_sequence = created_children[-1].sequence or base_sequence
    downstream = (
        db.query(Ticket)
        .filter(Ticket.conversation_id == conversation_id, Ticket.id != ticket.id)
        .all()
    )
    for row in downstream:
        deps = list(row.depends_on or [])
        if ticket.ticket_id not in deps:
            continue

        row.depends_on = _dedupe_keep_order([
            final_child_id if dep == ticket.ticket_id else dep
            for dep in deps
        ])
        if row.status == "pending" and row.sequence is not None and row.sequence <= final_child_sequence:
            row.sequence = final_child_sequence + 1
        row.updated_at = now

    db.commit()
    for child in created_children:
        db.refresh(child)

    # Best-effort Jira mirroring for split children so the board stays in sync.
    if conversation.jira_project_key:
        try:
            from services.jira_service import push_tickets_to_jira

            jira_payload = [
                {
                    "id": c.ticket_id,
                    "type": c.type,
                    "title": c.title,
                    "description": c.description,
                    "priority": c.priority or "Medium",
                    "phase": c.phase,
                    "sequence": c.sequence,
                    "dependsOn": c.depends_on or [],
                    "storyPoints": c.story_points,
                    "labels": c.labels or [],
                }
                for c in created_children
            ]

            jira_results = await push_tickets_to_jira(
                user_id=user_id,
                db=db,
                tickets=jira_payload,
                project_key=conversation.jira_project_key,
            )

            key_by_ticket_id = {
                r.get("ticket_id"): r.get("key")
                for r in jira_results
                if isinstance(r, dict) and r.get("ticket_id") and r.get("key")
            }

            mirrored = 0
            for child in created_children:
                jira_key = key_by_ticket_id.get(child.ticket_id)
                if jira_key:
                    child.jira_issue_key = jira_key
                    child.updated_at = datetime.utcnow()
                    mirrored += 1

            if mirrored:
                db.commit()

            failed = [r for r in jira_results if isinstance(r, dict) and "error" in r]
            if failed:
                logger.warning(
                    "Auto-split Jira mirroring partial failure for %s: %d/%d created.",
                    ticket.ticket_id,
                    mirrored,
                    len(created_children),
                )
        except Exception as exc:
            logger.warning(
                "Auto-split Jira mirroring failed for %s: %s",
                ticket.ticket_id,
                exc,
            )

    logger.info(
        "Auto-split applied for %s (attempt=%d): %s",
        ticket.ticket_id,
        next_attempt,
        [c.ticket_id for c in created_children],
    )
    return True


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

    # ── Cancellation check (before doing any work) ────────────────────────────
    db.refresh(conversation)
    if conversation.cancelled:
        logger.info(
            "Ticket %s skipped — conversation %s was cancelled.",
            ticket.ticket_id, conversation.id,
        )
        ticket.status     = "cancelled"
        ticket.updated_at = datetime.utcnow()
        db.commit()
        return False

    logger.info(
        "Running ticket %s (%s) seq=%s — %s",
        ticket.ticket_id, ticket.type, ticket.sequence, ticket.title,
    )

    from models.jira_token import JiraToken

    # ── Atomically claim the ticket ───────────────────────────────────────────
    # Two concurrent background tasks can both see the same ticket as 'pending'.
    # Using UPDATE WHERE status='pending' ensures only ONE task can claim it —
    # the other will get 0 rows_affected and skip it cleanly.
    rows_claimed = (
        db.query(Ticket)
        .filter(Ticket.id == ticket_db_id, Ticket.status == "pending")
        .update({"status": "in_progress", "updated_at": datetime.utcnow()}, synchronize_session=False)
    )
    db.commit()
    if rows_claimed == 0:
        logger.warning(
            "Ticket %s (db_id=%s) already claimed by another runner — skipping.",
            ticket.ticket_id, ticket_db_id,
        )
        return False
    db.refresh(ticket)  # reload after the atomic update

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
            logger.info(
                "Dispatching ticket %s to BACKEND agent (repo=%s).",
                ticket.ticket_id, repo_name,
            )
            result = await be_svc.run_backend_task(
                ticket=ticket,
                ticket_prompt=ticket_prompt,
                repo_name=repo_name,
            )
        else:
            logger.info(
                "Dispatching ticket %s to FRONTEND agent (type=%s, repo=%s).",
                ticket.ticket_id, ticket.type, repo_name,
            )
            result = await fe_svc.run_frontend_task(
                ticket=ticket,
                ticket_prompt=ticket_prompt,
                repo_name=repo_name,
            )

        # ── Post-agent cancellation check ─────────────────────────────────────
        # Cancellation may have been requested while the LLM was running.
        # Re-fetch the conversation to get the latest flag value.
        db.refresh(conversation)
        if conversation.cancelled:
            logger.info(
                "Ticket %s agent completed but conversation %s was cancelled — discarding results.",
                ticket.ticket_id, conversation.id,
            )
            ticket.status     = "cancelled"
            ticket.updated_at = datetime.utcnow()
            db.commit()
            return False

        # Check for partial failures (files that failed to write to GitHub)
        file_errors = result.get("file_errors", [])
        if file_errors:
            logger.warning(
                "Ticket %s completed with %d file write failure(s): %s",
                ticket.ticket_id, len(file_errors), file_errors,
            )

        ticket.agent_output = json.dumps(result)
        ticket.status       = "done"
        ticket.updated_at   = datetime.utcnow()
        db.commit()

        logger.info(
            "Ticket %s done. Files written: %d, file errors: %d, branch: %s.",
            ticket.ticket_id,
            result.get("files_written", 0),
            len(file_errors),
            result.get("branch", "?"),
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
        # Determine the failure stage from the exception context
        stage = "agent_execution"
        exc_type = type(exc).__name__
        if "anthropic" in type(exc).__module__.lower() if hasattr(type(exc), '__module__') and type(exc).__module__ else False:
            stage = "llm_api_call"
        elif "github" in str(exc).lower() or "requests" in exc_type.lower():
            stage = "github_write"
        elif "json" in exc_type.lower() or "parse" in str(exc).lower():
            stage = "output_parsing"

        error_msg = _build_error_msg(exc, stage)
        logger.exception(
            "Ticket %s failed at stage '%s': %s",
            ticket.ticket_id, stage, exc,
        )
        ticket.status     = "failed"
        ticket.error_msg  = error_msg
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
        # Re-fetch the conversation each wave so we always see the latest cancelled flag
        db.refresh(conversation)
        if conversation.cancelled:
            logger.info(
                "Agent pipeline halted — conversation %s was cancelled.", conversation_id
            )
            break

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
        for i, outcome in enumerate(results):
            t = batch[i]
            if outcome is True:
                done_count += 1
                continue

            if isinstance(outcome, Exception):
                # asyncio.gather caught an unhandled exception
                ticket_row = db.get(Ticket, t.id)
                if ticket_row and ticket_row.status != "failed":
                    ticket_row.status    = "failed"
                    ticket_row.error_msg = _build_error_msg(outcome, "unhandled_gather_exception")
                    ticket_row.updated_at = datetime.utcnow()
                    db.commit()
                logger.exception(
                    "Unhandled exception in asyncio.gather for ticket %s: %s",
                    t.ticket_id, outcome,
                )

            ticket_row = db.get(Ticket, t.id)
            split_recovered = False
            if ticket_row:
                split_recovered = await _auto_split_failed_ticket(
                    conversation_id,
                    ticket_row,
                    user_id,
                    conversation,
                    db,
                )

            if split_recovered:
                logger.info(
                    "Recovered oversized ticket %s via auto-split.",
                    t.ticket_id,
                )
                continue

            fail_count += 1

    all_tickets   = db.query(Ticket).filter(Ticket.conversation_id == conversation_id).all()
    still_pending = sum(1 for t in all_tickets if t.status in ("pending", "in_progress"))
    all_failed    = sum(1 for t in all_tickets if t.status == "failed")

    logger.info(
        "run_all_tickets for conversation %s complete — done=%d failed=%d still_pending=%d",
        conversation_id, done_count, fail_count, still_pending,
    )

    # ── Post-completion: Netlify deployment + README (only when every ticket is done) ─────
    if still_pending == 0 and all_failed == 0 and conversation.github_repo_name:
        import os
        from services.github_service import write_file_to_repo

        repo     = conversation.github_repo_name
        org_name = os.getenv("GITHUB_ORG", "AI-Factory-Repos")

        # Derive project type from the PM-assigned tags stored on the conversation.
        # Fall back to inspecting ticket types for older rows that pre-date tagging.
        project_tags: dict[str, bool] = conversation.project_tags or {}
        if project_tags:
            has_frontend           = project_tags.get("has_frontend",           False)
            has_backend            = project_tags.get("has_backend",            False)
            is_script              = project_tags.get("is_script",              False)
            is_mobile_app          = project_tags.get("is_mobile_app",          False)
            is_devops_program      = project_tags.get("is_devops_program",      False)
            is_full_stack          = project_tags.get("is_full_stack",          False)
            has_mixed_technologies = project_tags.get("has_mixed_technologies",  False)
        else:
            # Legacy fallback: derive from ticket types
            has_frontend           = any(t.type == "frontend" for t in all_tickets)
            has_backend            = any(t.type == "backend"  for t in all_tickets)
            is_script              = False
            is_mobile_app          = False
            is_devops_program      = False
            is_full_stack          = has_frontend and has_backend
            has_mixed_technologies = False

        logger.info(
            "All tickets done for conversation %s — running post-completion steps for %s "
            "(has_frontend=%s, has_backend=%s, is_full_stack=%s, is_script=%s, "
            "is_mobile_app=%s, is_devops_program=%s, has_mixed_technologies=%s).",
            conversation_id, repo,
            has_frontend, has_backend, is_full_stack,
            is_script, is_mobile_app, is_devops_program, has_mixed_technologies,
        )

        repo_full_name = f"{org_name}/{repo}"
        repo_github_url = f"https://github.com/{org_name}/{repo}"

        # ── Double-Step Deployment ────────────────────────────────────────────
        #
        # For full-stack projects the deployment order is strictly:
        #
        #   Step 1 — Railway: create a service in the Production Hub and capture
        #             the public backend URL before any frontend config is written.
        #
        #   Step 2 — Write netlify.toml to GitHub with the real Railway URL so
        #             the /api/* proxy is set correctly BEFORE Netlify builds.
        #
        #   Step 3 — Create the Netlify site; its FIRST build reads netlify.toml
        #             from the repo and uses the correct proxy immediately.
        #
        # This avoids a second Netlify build solely to fix the proxy target.

        # ── Step 1: Deploy backend to Railway ────────────────────────────────
        backend_url: str | None = None
        if has_backend:
            try:
                from infrastructure.railway_client import (
                    create_production_service,
                    RailwayError,
                    RailwayConflictError,
                    RailwayAuthError,
                    RailwayRateLimitError,
                )
                backend_url = create_production_service(
                    repo_url=repo_github_url,
                    service_name=repo,
                )
                logger.info(
                    "Step 1 ✓ Railway backend live for %s → %s", repo, backend_url,
                )
            except RailwayConflictError as exc:
                logger.error(
                    "Railway service name '%s' already exists in the Production Hub. "
                    "Skipping Railway deployment — netlify.toml proxy will be omitted. "
                    "Details: %s",
                    repo, exc,
                )
            except RailwayAuthError as exc:
                logger.error(
                    "Railway auth error for %s: %s — "
                    "check RAILWAY_API_TOKEN in .env.", repo, exc,
                )
            except RailwayRateLimitError as exc:
                logger.error(
                    "Railway rate limit hit for %s: %s — "
                    "the factory will continue without Railway deployment.", repo, exc,
                )
            except RailwayError as exc:
                logger.error(
                    "Railway deployment failed for %s: %s — "
                    "continuing without backend URL.", repo, exc,
                )
            except Exception as exc:
                logger.exception(
                    "Unexpected error during Railway deployment for %s: %s", repo, exc,
                )

        # ── Step 2: Write netlify.toml to GitHub (full-stack only) ───────────
        # Must happen BEFORE the Netlify site is created so the proxy config
        # is in the repo when Netlify's first build runs.
        if is_full_stack and has_frontend:
            if backend_url:
                try:
                    from services.netlify_service import write_netlify_toml
                    ok = write_netlify_toml(repo_name=repo, backend_url=backend_url)
                    if ok:
                        logger.info(
                            "Step 2 ✓ netlify.toml committed to %s (proxy → %s).",
                            repo, backend_url,
                        )
                    else:
                        logger.warning(
                            "Step 2 ✗ netlify.toml write failed for %s — "
                            "Netlify will build without proxy config.", repo,
                        )
                except Exception as exc:
                    logger.exception(
                        "Failed to write netlify.toml for %s: %s", repo, exc,
                    )
            else:
                logger.warning(
                    "Step 2 skipped — no backend_url available for %s. "
                    "netlify.toml proxy will not be configured.", repo,
                )

        # ── Step 3: Create Netlify site ───────────────────────────────────────
        # netlify.toml is already in the repo; Netlify reads it on first build.
        live_url: str | None = None
        if has_frontend:
            try:
                from services.netlify_service import create_netlify_site
                netlify_result = create_netlify_site(
                    site_name=repo,
                    repo_full_name=repo_full_name,
                )
                if netlify_result:
                    live_url = netlify_result["site_url"]
                    logger.info(
                        "Step 3 ✓ Netlify site ready for %s → %s", repo, live_url,
                    )
                else:
                    logger.warning(
                        "Step 3 ✗ Netlify site creation returned None for %s — "
                        "README will omit the live URL.", repo,
                    )
            except Exception as exc:
                logger.exception(
                    "Failed to create Netlify site for %s: %s", repo, exc,
                )
        else:
            logger.info(
                "has_frontend=False for %s — skipping Netlify deployment.", repo,
            )

        # 2. Generate and commit a README.md from the chat history.
        # Build history and project_name here so the CLAUDE.md block below can reuse them.
        from models.message import Message

        msgs = (
            db.query(Message)
            .filter(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
            .all()
        )
        history = [
            {"role": "user" if m.role == "user" else "assistant", "content": m.content}
            for m in msgs
        ]
        # Derive a human-friendly project name from the repo slug
        project_name = repo.replace("-", " ").title()

        try:
            from services.pm_agent import generate_readme

            logger.info("Generating README.md for %s (live_url=%s) …", repo, live_url)
            readme_md = generate_readme(
                history,
                project_name=project_name,
                live_url=live_url,
            )

            ok = write_file_to_repo(
                repo_name=repo,
                file_path="README.md",
                content=readme_md,
                branch="main",
                commit_message="AI Agent: add project README.md",
            )
            if ok:
                logger.info("README.md committed to %s (includes live URL: %s).", repo, live_url)
            else:
                logger.warning("Failed to write README.md to %s.", repo)
        except Exception as exc:
            logger.exception(
                "Failed to generate/commit README.md for %s: %s", repo, exc,
            )

        # 3. Generate and commit CLAUDE.md — full technical context for future AI agents
        try:
            from services.pm_agent import generate_claude_md

            # Build a lean ticket summary (skip raw agent_output to keep the prompt tight)
            ticket_summaries = [
                {
                    "id":          t.ticket_id,
                    "type":        t.type,
                    "phase":       t.phase,
                    "sequence":    t.sequence,
                    "title":       t.title,
                    "description": t.description,
                    "status":      t.status,
                }
                for t in all_tickets
            ]

            logger.info("Generating CLAUDE.md for %s …", repo)
            claude_md = generate_claude_md(
                history=history,
                tickets=ticket_summaries,
                project_name=project_name,
                live_url=live_url,
            )

            ok = write_file_to_repo(
                repo_name=repo,
                file_path="CLAUDE.md",
                content=claude_md,
                branch="main",
                commit_message="AI Agent: add CLAUDE.md project context",
            )
            if ok:
                logger.info("CLAUDE.md committed to %s.", repo)
            else:
                logger.warning("Failed to write CLAUDE.md to %s.", repo)
        except Exception as exc:
            logger.exception(
                "Failed to generate/commit CLAUDE.md for %s: %s", repo, exc,
            )

    # ── Update idea status based on final ticket outcomes ─────────────────────
    if conversation and conversation.idea_id:
        from models.idea import Idea
        idea = db.get(Idea, conversation.idea_id)
        if idea:
            if still_pending == 0 and all_failed == 0:
                idea.status = "completed"
            elif still_pending == 0 and done_count > 0:
                # Some done, some failed — still mark completed
                idea.status = "completed"
            elif still_pending == 0 and done_count == 0:
                # Everything failed — revert to pending so user can retry
                idea.status = "pending"
            db.commit()
            logger.info(
                "Idea %s status → %s (done=%d, failed=%d, pending=%d)",
                idea.id, idea.status, done_count, all_failed, still_pending,
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
