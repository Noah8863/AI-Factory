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
import re
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
    sequence (nulls last).  If ticket_type is given ('backend' | 'frontend' | 'script'),
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
    if not msg:
        return False

    explicit_markers = (
        "max_tokens",
        "max token",
        "token limit",
        "maximum token",
        "maximum output",
        "output token",
    )
    if any(marker in msg for marker in explicit_markers):
        return True

    return "truncat" in msg and "token" in msg


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


def _extract_backend_routes_from_text(content: str) -> list[tuple[str, str]]:
    """Extract likely API routes from backend source text."""
    if not content:
        return []

    routes: list[tuple[str, str]] = []

    # Express style: app.get('/path'), router.post('/path')
    for method, path in re.findall(
        r"\b(?:app|router)\.(get|post|put|patch|delete)\(\s*['\"]([^'\"]+)['\"]",
        content,
        flags=re.IGNORECASE,
    ):
        if path.startswith("/"):
            routes.append((method.upper(), path))

    # FastAPI style: @app.get('/path'), @router.post('/path')
    for method, path in re.findall(
        r"@\s*(?:app|router)\.(get|post|put|patch|delete)\(\s*['\"]([^'\"]+)['\"]",
        content,
        flags=re.IGNORECASE,
    ):
        if path.startswith("/"):
            routes.append((method.upper(), path))

    # Basic Node http server style: if (url === '/api/ip')
    for path in re.findall(
        r"\burl\s*===\s*['\"]([^'\"]+)['\"]",
        content,
        flags=re.IGNORECASE,
    ):
        if path.startswith("/"):
            routes.append(("ANY", path))

    deduped: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for method, path in routes:
        key = (method, path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(key)
    return deduped


def _build_backend_api_contract(conversation_id: int, db: Session, max_routes: int = 40) -> str:
    """
    Build an API contract summary from completed backend ticket outputs.

    This is passed into frontend prompts so frontend code uses implemented
    backend routes instead of inventing endpoint names.
    """
    backend_done = (
        db.query(Ticket)
        .filter(
            Ticket.conversation_id == conversation_id,
            Ticket.type == "backend",
            Ticket.status == "done",
        )
        .order_by(Ticket.sequence.asc().nullslast(), Ticket.id.asc())
        .all()
    )

    if not backend_done:
        return ""

    route_entries: list[tuple[str, str, str]] = []  # (method, path, source)
    seen_routes: set[tuple[str, str]] = set()

    for ticket in backend_done:
        if not ticket.agent_output:
            continue
        try:
            payload = json.loads(ticket.agent_output)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue

        for file_obj in payload.get("files", []) or []:
            if not isinstance(file_obj, dict):
                continue

            path = str(file_obj.get("path", "")).replace("\\", "/").strip("/")
            content = str(file_obj.get("content", "") or "")
            if not content:
                continue

            for method, route_path in _extract_backend_routes_from_text(content):
                route_key = (method, route_path)
                if route_key in seen_routes:
                    continue
                seen_routes.add(route_key)
                route_entries.append((method, route_path, path or f"{ticket.ticket_id}"))

    if not route_entries:
        return ""

    lines = [
        f"- `{method} {route}` from `{source}`"
        for method, route, source in route_entries[:max_routes]
    ]
    joined = "\n".join(lines)
    return (
        "## Backend API Contract (from completed backend tickets)\n\n"
        "These routes are already implemented in backend code. Reuse them exactly "
        "for frontend API calls unless this ticket explicitly requires backend API changes.\n\n"
        f"{joined}\n\n"
    )


_BACKEND_ENTRY_NAMES = frozenset({"app", "server", "main", "index"})
_BACKEND_ROUTE_KEYWORDS = ("route", "router", "controller", "handler", "api", "auth", "endpoint")


def _backend_file_priority(path: str) -> int:
    stem = path.lower().rsplit("/", 1)[-1].rsplit(".", 1)[0]
    if stem in _BACKEND_ENTRY_NAMES:
        return 0
    if any(kw in path.lower() for kw in _BACKEND_ROUTE_KEYWORDS):
        return 1
    return 2


async def _fetch_backend_source_context(
    repo_name: str,
    existing_repo_files: list[str],
    max_files: int = 6,
    max_lines_per_file: int = 150,
) -> str:
    """
    Fetch the content of key backend files already committed to GitHub and return
    a formatted context block for inclusion in frontend agent prompts.

    Giving the frontend agent actual source code means it sees full route prefixes
    (e.g. app.use('/api', router)) and request/response shapes, not just filenames.
    """
    if not repo_name or not existing_repo_files:
        return ""

    backend_files = [
        f for f in existing_repo_files
        if f.startswith("backend/")
        and not f.endswith((".md", ".json", ".lock", ".env", ".yaml", ".yml", ".txt"))
    ]
    if not backend_files:
        return ""

    selected = sorted(backend_files, key=_backend_file_priority)[:max_files]

    from services.github_service import read_file_from_repo

    sections: list[str] = []
    for file_path in selected:
        try:
            content = await asyncio.to_thread(read_file_from_repo, repo_name, file_path)
            if not content or not content.strip():
                continue
            lines = content.splitlines()
            truncated = len(lines) > max_lines_per_file
            if truncated:
                lines = lines[:max_lines_per_file]
            body = "\n".join(lines)
            if truncated:
                body += f"\n... (truncated — {len(content.splitlines()) - max_lines_per_file} more lines)"
            sections.append(f"### `{file_path}`\n```\n{body}\n```")
        except Exception as exc:
            logger.debug("Could not fetch backend file %s for frontend context: %s", file_path, exc)

    if not sections:
        return ""

    joined = "\n\n".join(sections)
    return (
        "## Backend Source Files (actual committed code)\n\n"
        "These files are already live in the repository. "
        "You MUST use the exact routes, URL prefixes, and request/response shapes shown here "
        "for all frontend API calls. Never invent or guess endpoint paths — "
        "read `app.use(...)` calls to determine full prefixes, then read the route handlers "
        "for method + path details.\n\n"
        f"{joined}\n\n"
    )


_FRONTEND_ENTRY_NAMES = frozenset({"index", "app", "main", "router"})
_FRONTEND_LAYOUT_KEYWORDS = ("nav", "navbar", "header", "footer", "layout", "sidebar", "menu", "shell")


def _frontend_file_priority(path: str) -> int:
    filename = path.lower().rsplit("/", 1)[-1]
    stem = filename.rsplit(".", 1)[0]
    if stem in _FRONTEND_ENTRY_NAMES:
        return 0
    if any(kw in path.lower() for kw in _FRONTEND_LAYOUT_KEYWORDS):
        return 1
    return 2


async def _fetch_frontend_source_context(
    repo_name: str,
    existing_repo_files: list[str],
    max_files: int = 8,
    max_lines_per_file: int = 150,
) -> str:
    """
    Fetch the content of already-committed frontend files and return a formatted
    context block for later frontend ticket prompts.

    This prevents frontend agents from ignoring files created by earlier tickets —
    e.g. a ticket that builds a navbar will see its own HTML so subsequent tickets
    can add links to it rather than creating duplicate nav elements.
    """
    if not repo_name or not existing_repo_files:
        return ""

    frontend_files = [
        f for f in existing_repo_files
        if f.startswith("frontend/")
        and not f.endswith((".md", ".json", ".lock", ".env"))
    ]
    if not frontend_files:
        return ""

    selected = sorted(frontend_files, key=_frontend_file_priority)[:max_files]

    from services.github_service import read_file_from_repo

    sections: list[str] = []
    for file_path in selected:
        try:
            content = await asyncio.to_thread(read_file_from_repo, repo_name, file_path)
            if not content or not content.strip():
                continue
            lines = content.splitlines()
            truncated = len(lines) > max_lines_per_file
            if truncated:
                lines = lines[:max_lines_per_file]
            body = "\n".join(lines)
            if truncated:
                body += f"\n... (truncated — {len(content.splitlines()) - max_lines_per_file} more lines)"
            sections.append(f"### `{file_path}`\n```\n{body}\n```")
        except Exception as exc:
            logger.debug("Could not fetch frontend file %s for context: %s", file_path, exc)

    if not sections:
        return ""

    joined = "\n\n".join(sections)
    return (
        "## Existing Frontend Files (already committed)\n\n"
        "These files were written by earlier tickets and are already in the repository. "
        "You MUST read them before writing any new files:\n"
        "- If a nav/header/layout file exists, UPDATE it to add links for new pages — do not create a second nav.\n"
        "- If an index.html or router exists, UPDATE it to register new pages/routes.\n"
        "- Reuse shared CSS classes, variable names, and patterns already established.\n"
        "- Never duplicate structure that already exists — extend it.\n\n"
        f"{joined}\n\n"
    )


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

    # Keep Jira board state aligned: the superseded parent ticket is now
    # considered resolved by auto-split, so move its Jira issue to Done.
    if ticket.jira_issue_key:
        try:
            from models.jira_token import JiraToken
            from services.jira_service import transition_jira_issue

            token_row = db.query(JiraToken).filter(JiraToken.user_id == user_id).first()
            cloud_id = token_row.jira_cloud_id if token_row else None
            if cloud_id:
                await transition_jira_issue(
                    user_id=user_id,
                    db=db,
                    cloud_id=cloud_id,
                    issue_key=ticket.jira_issue_key,
                    target_status="Done",
                )
            else:
                logger.warning(
                    "Auto-split parent %s has Jira key %s but no cloud_id was found.",
                    ticket.ticket_id,
                    ticket.jira_issue_key,
                )
        except Exception as exc:
            logger.warning(
                "Failed to transition auto-split parent Jira issue for %s: %s",
                ticket.ticket_id,
                exc,
            )

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
    from services import script_agent as sc_svc
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
    project_tags = conversation.project_tags or {}
    has_frontend_tag = bool(project_tags.get("has_frontend", False))
    has_backend_tag = bool(project_tags.get("has_backend", False))
    is_pure_script_project = bool(project_tags.get("is_script", False)) and not (
        has_frontend_tag or has_backend_tag
    )
    effective_ticket_type = "script" if is_pure_script_project else ticket.type

    if effective_ticket_type != ticket.type:
        logger.info(
            "Ticket %s type overridden from %s to %s due project tags.",
            ticket.ticket_id,
            ticket.type,
            effective_ticket_type,
        )

    # Include repository file-tree context so agents can update existing files
    # with exact paths instead of inventing new placeholders.
    existing_repo_files: list[str] = []
    if repo_name:
        try:
            from services.github_service import list_repo_files

            existing_repo_files = await asyncio.to_thread(
                list_repo_files,
                repo_name,
                "main",
                300,
            )
        except Exception as exc:
            logger.warning(
                "Could not load repository file tree for %s before ticket %s: %s",
                repo_name,
                ticket.ticket_id,
                exc,
            )

    if existing_repo_files:
        repo_file_lines = "\n".join(f"- {path}" for path in existing_repo_files)
        repo_files_block = (
            "## Existing Repository Files (main branch)\n\n"
            "Use these exact paths when updating files.\n\n"
            f"{repo_file_lines}\n\n"
        )
    else:
        repo_files_block = (
            "## Existing Repository Files (main branch)\n\n"
            "Repository currently appears empty or file listing was unavailable.\n\n"
        )

    backend_api_contract_block = ""
    frontend_source_block = ""
    if effective_ticket_type == "frontend":
        # Fetch actual committed backend source files — gives the frontend agent full
        # route prefixes (e.g. app.use('/api', router)) and request/response shapes.
        source_context = await _fetch_backend_source_context(repo_name, existing_repo_files)
        # Also build the compact regex-extracted route list from stored agent output.
        route_contract = _build_backend_api_contract(conversation.id, db)

        if source_context:
            backend_api_contract_block = source_context
            if route_contract:
                backend_api_contract_block += route_contract
        elif route_contract:
            backend_api_contract_block = route_contract
        else:
            backend_api_contract_block = (
                "## Backend API Contract (from completed backend tickets)\n\n"
                "No completed backend API routes were detected yet. If this ticket needs API "
                "integration, reuse existing backend paths from repository files and avoid "
                "inventing new endpoint names.\n\n"
            )

        # Fetch already-committed frontend files so the agent sees existing nav/layout
        # structure and extends it rather than ignoring or duplicating it.
        frontend_source_block = await _fetch_frontend_source_context(repo_name, existing_repo_files)

    # Blueprint block — shared across all ticket types so BE and FE agents
    # build toward the same pages, routes, data shapes, and integration contract.
    blueprint_block = ""
    if conversation.project_blueprint:
        blueprint_block = (
            "## Project Blueprint\n\n"
            "This is the authoritative architectural plan for the entire project. "
            "All agents implement against this shared contract — do not deviate from "
            "the routes, pages, data models, or integration patterns defined here.\n\n"
            f"{conversation.project_blueprint}\n\n"
        )

    # Build a rich prompt from ticket metadata
    deps_str = ", ".join(ticket.depends_on) if ticket.depends_on else "none"
    ticket_prompt = (
        f"# Ticket {ticket.ticket_id}: {ticket.title}\n\n"
        f"**Phase:** {ticket.phase or 'N/A'} | "
        f"**Priority:** {ticket.priority or 'N/A'} | "
        f"**Sequence:** {ticket.sequence or 'N/A'} | "
        f"**Depends on:** {deps_str}\n\n"
        f"{blueprint_block}"
        "## Implementation Guardrails\n\n"
        "- The ticket title is only a short label.\n"
        "- Acceptance Criteria below is the source of truth and must drive implementation details.\n"
        "- Do not generate placeholder/demo artifacts (for example HelloWorld, demo-only components, or toy scaffolds) unless explicitly required by the criteria.\n\n"
        "- For frontend tickets, follow the Backend API Contract routes exactly when provided.\n\n"
        f"{repo_files_block}"
        f"{frontend_source_block}"
        f"{backend_api_contract_block}"
        f"## Acceptance Criteria\n\n{ticket.description}\n\n"
        f"## Target Repository\n`{repo_name}`\n"
    )

    try:
        if effective_ticket_type == "backend":
            logger.info(
                "Dispatching ticket %s to BACKEND agent (repo=%s).",
                ticket.ticket_id, repo_name,
            )
            result = await be_svc.run_backend_task(
                ticket=ticket,
                ticket_prompt=ticket_prompt,
                repo_name=repo_name,
                skip_ci_commits=True,
            )
        elif effective_ticket_type == "frontend":
            logger.info(
                "Dispatching ticket %s to FRONTEND agent (type=%s, repo=%s).",
                ticket.ticket_id, effective_ticket_type, repo_name,
            )
            result = await fe_svc.run_frontend_task(
                ticket=ticket,
                ticket_prompt=ticket_prompt,
                repo_name=repo_name,
                skip_ci_commits=True,
            )
        elif effective_ticket_type == "script":
            logger.info(
                "Dispatching ticket %s to SCRIPT agent (repo=%s).",
                ticket.ticket_id, repo_name,
            )
            result = await sc_svc.run_script_task(
                ticket=ticket,
                ticket_prompt=ticket_prompt,
                repo_name=repo_name,
                existing_repo_files=existing_repo_files,
                skip_ci_commits=True,
            )
        else:
            raise RuntimeError(
                f"Unsupported ticket type '{effective_ticket_type}' for ticket {ticket.ticket_id}."
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
    allow_incomplete_deploy: bool = False,
    force_post_completion: bool = False,
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

    # ── Generate project blueprint (once, before first ticket fires) ─────────
    # The blueprint gives every agent a shared mental model: pages, endpoints,
    # data models, and integration contract.  We generate it here rather than
    # in start_tasking so it does not add latency to the HTTP response.
    if not conversation.project_blueprint:
        try:
            from services.pm_agent import generate_project_blueprint

            all_conv_tickets = (
                db.query(Ticket)
                .filter(Ticket.conversation_id == conversation_id)
                .all()
            )
            tickets_for_blueprint = [
                {
                    "id": t.ticket_id,
                    "type": t.type,
                    "title": t.title,
                    "description": t.description or "",
                }
                for t in all_conv_tickets
            ]
            project_name = (
                (conversation.github_repo_name or "project")
                .replace("-", " ")
                .title()
            )
            blueprint = await asyncio.to_thread(
                generate_project_blueprint,
                {"tickets": tickets_for_blueprint},
                conversation.project_tags or {},
                project_name,
            )
            if blueprint:
                conversation.project_blueprint = blueprint
                conversation.updated_at = datetime.utcnow()
                db.commit()
                logger.info(
                    "Project blueprint generated for conversation %s (%d chars).",
                    conversation_id,
                    len(blueprint),
                )
        except Exception as exc:
            logger.warning(
                "Blueprint generation failed for conversation %s — agents will proceed without it: %s",
                conversation_id,
                exc,
            )

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

        project_tags = conversation.project_tags or {}
        prefer_backend_first = bool(
            project_tags.get("has_frontend", False)
            and project_tags.get("has_backend", False)
        )
        if prefer_backend_first:
            runnable_backend = [t for t in runnable if t.type == "backend"]
            if runnable_backend:
                logger.info(
                    "Backend-first handoff enabled for conversation %s; prioritizing backend wave: %s",
                    conversation_id,
                    [t.ticket_id for t in runnable_backend],
                )
                runnable = runnable_backend

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
    total_tickets = len(all_tickets)
    all_done      = total_tickets > 0 and all(t.status == "done" for t in all_tickets)

    logger.info(
        "run_all_tickets for conversation %s complete — done=%d failed=%d still_pending=%d",
        conversation_id, done_count, fail_count, still_pending,
    )

    # ── Post-completion: Netlify deployment + README ─────────────────────────────
    made_ticket_progress = (done_count + fail_count) > 0

    should_attempt_auto_post_completion = (
        all_done
        and conversation.deployment_status in (None, "", "not_deployed", "failed")
    )

    should_run_post_completion = (
        conversation.github_repo_name
        and (all_done or allow_incomplete_deploy)
        and (
            force_post_completion
            or made_ticket_progress
            or should_attempt_auto_post_completion
        )
    )

    if should_run_post_completion:
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
            has_mixed_technologies = project_tags.get("has_mixed_technologies",  False)
        else:
            # Legacy fallback: derive from ticket types
            has_frontend           = any(t.type == "frontend" for t in all_tickets)
            has_backend            = any(t.type == "backend"  for t in all_tickets)
            is_script              = any(t.type == "script" for t in all_tickets)
            is_mobile_app          = False
            is_devops_program      = False
            has_mixed_technologies = False

        # Never trust persisted is_full_stack blindly; derive from FE+BE tags.
        is_full_stack = has_frontend and has_backend

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
        should_deploy_to_netlify = has_frontend or is_full_stack
        deployment_error: str | None = None

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
        if should_deploy_to_netlify:
            conversation.deployment_status = "deploying"
            conversation.deployment_error = None
            conversation.updated_at = datetime.utcnow()
            db.commit()

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

        # ── Step 2: Write netlify.toml to GitHub (all frontend projects) ─────
        # Must happen BEFORE the Netlify site is created so build settings are
        # present on first clone. For full-stack projects we also include the
        # /api proxy when backend_url is available.
        if has_frontend:
            try:
                from services.netlify_service import write_netlify_toml

                proxy_url = backend_url if (is_full_stack and backend_url) else None
                ok = write_netlify_toml(repo_name=repo, backend_url=proxy_url)
                if ok:
                    if proxy_url:
                        logger.info(
                            "Step 2 ✓ netlify.toml committed to %s (proxy → %s).",
                            repo,
                            proxy_url,
                        )
                    else:
                        logger.info(
                            "Step 2 ✓ netlify.toml committed to %s (frontend build config only).",
                            repo,
                        )
                else:
                    logger.warning(
                        "Step 2 ✗ netlify.toml write failed for %s.",
                        repo,
                    )
            except Exception as exc:
                logger.exception(
                    "Failed to write netlify.toml for %s: %s",
                    repo,
                    exc,
                )

        # ── Step 3: Create Netlify site ───────────────────────────────────────
        # netlify.toml is already in the repo; Netlify reads it on first build.
        live_url: str | None = None
        if should_deploy_to_netlify:
            # Safety: legacy repos may already exist as private from older runs.
            # Ensure public visibility before Netlify attempts to clone.
            try:
                from services.github_service import ensure_repo_public

                if not ensure_repo_public(repo):
                    logger.warning(
                        "Could not verify public visibility for %s before Netlify create; "
                        "build prep may fail if repo remains private.",
                        repo,
                    )
            except Exception as exc:
                logger.warning(
                    "Repo visibility check failed for %s before Netlify create: %s",
                    repo,
                    exc,
                )

            try:
                from services.netlify_service import create_netlify_site
                netlify_result = create_netlify_site(
                    site_name=repo,
                    repo_full_name=repo_full_name,
                )
                live_url = (netlify_result or {}).get("site_url")
                if live_url:
                    logger.info(
                        "Step 3 ✓ Netlify site ready for %s → %s", repo, live_url,
                    )
                else:
                    deployment_error = (
                        (netlify_result or {}).get("error")
                        or "Netlify site creation returned no live URL."
                    )
                    logger.warning(
                        "Step 3 ✗ Netlify site was not ready for %s: %s",
                        repo,
                        deployment_error,
                    )
            except Exception as exc:
                deployment_error = f"Netlify site creation failed: {exc}"
                logger.exception(
                    "Failed to create Netlify site for %s: %s", repo, exc,
                )
        else:
            logger.info(
                "Skipping Netlify deployment for %s — project is neither frontend nor full-stack.", repo,
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

        # Build a compact implementation handoff from developer agent outputs
        # so README generation reflects what was actually created.
        implementation_handoff: list[dict] = []
        for t in sorted(all_tickets, key=lambda row: (row.sequence or 999, row.ticket_id or "")):
            output = {}
            if t.agent_output:
                try:
                    parsed = json.loads(t.agent_output)
                    if isinstance(parsed, dict):
                        output = parsed
                except Exception:
                    output = {}

            generated_files: list[str] = []
            for f in output.get("files", []) or []:
                if not isinstance(f, dict):
                    continue
                path = str(f.get("path", "")).replace("\\", "/").strip("/")
                if path:
                    generated_files.append(path)

            implementation_handoff.append(
                {
                    "id": t.ticket_id,
                    "type": t.type,
                    "phase": t.phase,
                    "sequence": t.sequence,
                    "title": t.title,
                    "status": t.status,
                    "summary": str(output.get("summary", "") or ""),
                    "notes": str(output.get("notes", "") or ""),
                    "generated_files": generated_files[:50],
                }
            )

        repo_files: list[str] = []
        try:
            from services.github_service import list_repo_files

            repo_files = await asyncio.to_thread(
                list_repo_files,
                repo,
                "main",
                500,
            )
        except Exception as exc:
            logger.warning(
                "Could not fetch repository tree for README generation in %s: %s",
                repo,
                exc,
            )

        try:
            from services.pm_agent import generate_readme

            logger.info("Generating README.md for %s (live_url=%s) …", repo, live_url)
            readme_md = generate_readme(
                history,
                project_name=project_name,
                live_url=live_url,
                project_tags={
                    "has_frontend": has_frontend,
                    "has_backend": has_backend,
                    "is_script": is_script,
                    "is_mobile_app": is_mobile_app,
                    "is_devops_program": is_devops_program,
                    "is_full_stack": is_full_stack,
                    "has_mixed_technologies": has_mixed_technologies,
                },
                repo_files=repo_files,
                implementation_handoff=implementation_handoff,
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
                commit_message="[skip ci] AI Agent: add CLAUDE.md project context",
            )
            if ok:
                logger.info("CLAUDE.md committed to %s.", repo)
            else:
                logger.warning("Failed to write CLAUDE.md to %s.", repo)
        except Exception as exc:
            logger.exception(
                "Failed to generate/commit CLAUDE.md for %s: %s", repo, exc,
            )

        if should_deploy_to_netlify:
            if live_url:
                conversation.deployment_status = "deployed"
                conversation.deployment_live_url = live_url
                conversation.deployment_error = None
            else:
                conversation.deployment_status = "failed"
                conversation.deployment_error = (
                    deployment_error
                    or "Deployment failed before a live URL was available."
                )
            conversation.updated_at = datetime.utcnow()
            db.commit()
    elif conversation.github_repo_name and (all_done or allow_incomplete_deploy):
        logger.info(
            "Skipping post-completion deploy/docs for conversation %s: no new ticket progress in this runner.",
            conversation_id,
        )

    # ── Update idea status based on final ticket outcomes ─────────────────────
    if not allow_incomplete_deploy and conversation and conversation.idea_id:
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

    if conversation.github_repo_name and not all_done and conversation.deployment_status == "deploying":
        conversation.deployment_status = "failed"
        conversation.deployment_error = (
            "Deployment skipped because not all Jira tickets are complete and passing."
        )
        conversation.updated_at = datetime.utcnow()
        db.commit()

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


async def run_deploy_and_docs_bg(
    conversation_id: int,
    user_id: int,
    allow_incomplete: bool = False,
) -> None:
    """
    Background wrapper for manual Deploy Idea / Redeploy Idea actions.

    Uses run_all_tickets with an optional deploy override so post-completion
    deploy/docs can run even when some tickets are failed (manual redeploy mode).
    """
    db = SessionLocal()
    try:
        await run_all_tickets(
            conversation_id,
            user_id,
            db,
            allow_incomplete_deploy=allow_incomplete,
            force_post_completion=True,
        )
    except Exception as exc:
        logger.exception(
            "Background deploy/docs run failed for conversation %s.",
            conversation_id,
        )
        conversation = db.get(Conversation, conversation_id)
        if conversation and conversation.deployment_status == "deploying":
            conversation.deployment_status = "failed"
            conversation.deployment_error = f"Manual deployment failed: {exc}"
            conversation.updated_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()
