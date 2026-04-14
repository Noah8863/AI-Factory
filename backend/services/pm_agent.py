"""
services/pm_agent.py
--------------------
I/O layer for the PM agent.
Reads ANTHROPIC_API_KEY from the backend .env file.
The system prompt and parser live in agents/pm_agent.py and are
never exposed to the frontend or to any client-side code.
"""

import logging
import os
import json
import re

from dotenv import load_dotenv
import anthropic

from agents.pm_agent import PM_SYSTEM_PROMPT, parse_agent_reply

load_dotenv()

logger = logging.getLogger(__name__)

_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
_MODEL  = "claude-sonnet-4-20250514"

# The exact message the route sends (and the system prompt expects) to trigger
# ticket generation.  Defined here so routes and tests can import it.
TASKING_ACTION_MESSAGE = "ACTION: Start tasking. Generate the Jira tickets now."

_TAG_KEYS = (
    "has_frontend",
    "has_backend",
    "is_script",
    "is_mobile_app",
    "is_devops_program",
    "is_full_stack",
    "has_mixed_technologies",
)

_ALLOWED_TICKET_TYPES = {"backend", "frontend", "script"}

_OVERSIZED_DESCRIPTION_CHARS = 1300
_OVERSIZED_TICKET_RE = re.compile(
    r"\b(polish|finalize|complete\s+all|end[-\s]?to[-\s]?end|entire\s+app|whole\s+app|everything\s+left)\b",
    re.IGNORECASE,
)

_TICKET_REBALANCE_SYSTEM_PROMPT = """
You are a ticket-plan rebalancer.

You receive a previously generated PM ticket JSON payload.
Rewrite it into a finer-grained, dependency-safe plan that avoids oversized
tickets that cause downstream developer max-token truncation.

Rules:
- Output only ONE JSON object in the same schema.
- Preserve project metadata (projectName, projectSummary, githubRepoName, jiraProjectKey, projectTags).
- Keep all seven projectTags keys and enforce is_full_stack = has_frontend AND has_backend.
- There is no hard maximum ticket count. Split broad tickets aggressively.
- Every ticket must be atomic and realistically finishable in 1 day (2 days max).
- Avoid catch-all tickets like "polish/finalize the whole app".
- Keep valid dependency ordering and sequence values.
- Use IDs like BE-N and FE-N with unique numbering.
- Every ticket labels list must include every projectTags key whose value is true.

Return JSON only. No prose.
"""

_FAILED_TICKET_SPLIT_SYSTEM_PROMPT = """
You are a recovery planner that splits one oversized engineering ticket into
smaller, sequential tickets to avoid model max-token truncation.

Return ONLY one JSON object in this exact shape:
{
  "splitTickets": [
    {
      "title": "string",
      "description": "string",
      "priority": "High|Medium|Low",
      "phase": "Foundation|Core|Integration|Polish"
    }
  ]
}

Rules:
- Output 2 to 4 splitTickets (never 1).
- Each ticket must be atomic and realistically finishable in <= 1 day.
- Keep acceptance criteria concise and implementation-focused.
- Avoid catch-all wording like "finalize everything" or "complete remaining app".
- Preserve the original ticket intent; do not add unrelated features.
- Keep priority/phase reasonable for each split.
"""

_IDEA_SUMMARY_SYSTEM_PROMPT = """
You are a concise product summary assistant.

Task:
- Summarize the user's project idea in one short sentence for a dashboard card.

Rules:
- 8 to 18 words preferred.
- Plain text only. No quotes, markdown, bullets, or prefixes.
- Focus on the product outcome (what is being built), not implementation detail.
"""

_PROJECT_TYPE_PREFIX_RE = re.compile(r"^\s*\[PROJECT_TYPE:\s*[^\]]+\]\s*", re.IGNORECASE)


def _parse_json_object(raw_text: str) -> dict | None:
    idx = raw_text.find("{")
    if idx >= 0:
        decoder = json.JSONDecoder()
        try:
            obj, _ = decoder.raw_decode(raw_text, idx)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass

    fenced = re.search(r"```(?:json)?\s*\n([\s\S]*?)\n```", raw_text)
    if fenced:
        try:
            obj = json.loads(fenced.group(1))
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            return None
    return None


def _strip_project_type_prefix(text: str) -> str:
    return _PROJECT_TYPE_PREFIX_RE.sub("", text or "").strip()


def split_ticket_for_recovery(ticket_payload: dict, max_parts: int = 3) -> list[dict]:
    """
    Split one oversized failed ticket into smaller tickets for auto-recovery.

    Returns a normalized list of split tickets, or [] when parsing/generation fails.
    """
    title = (ticket_payload.get("title") or "").strip()
    description = (ticket_payload.get("description") or "").strip()
    if not title or not description:
        return []

    max_parts = max(2, min(max_parts, 4))
    prompt = (
        "Split this failed oversized ticket into smaller sequential tickets.\n"
        f"Ticket ID: {ticket_payload.get('id', '')}\n"
        f"Type: {ticket_payload.get('type', '')}\n"
        f"Title: {title}\n"
        f"Priority: {ticket_payload.get('priority', 'Medium')}\n"
        f"Phase: {ticket_payload.get('phase', 'Core')}\n"
        f"Current sequence: {ticket_payload.get('sequence', '')}\n"
        f"DependsOn: {ticket_payload.get('dependsOn', [])}\n"
        f"Acceptance criteria:\n{description}\n\n"
        f"Return between 2 and {max_parts} splitTickets."
    )

    response = _client.messages.create(
        model=_MODEL,
        max_tokens=3072,
        system=_FAILED_TICKET_SPLIT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    parsed = _parse_json_object(response.content[0].text)
    if not isinstance(parsed, dict):
        return []

    raw_split = parsed.get("splitTickets")
    if not isinstance(raw_split, list):
        return []

    normalized: list[dict] = []
    allowed_priority = {"High", "Medium", "Low"}
    allowed_phase = {"Foundation", "Core", "Integration", "Polish"}
    fallback_priority = ticket_payload.get("priority") if ticket_payload.get("priority") in allowed_priority else "Medium"
    fallback_phase = ticket_payload.get("phase") if ticket_payload.get("phase") in allowed_phase else "Core"

    for item in raw_split:
        if not isinstance(item, dict):
            continue
        item_title = (item.get("title") or "").strip()
        item_desc = (item.get("description") or "").strip()
        if not item_title or not item_desc:
            continue

        item_priority = item.get("priority")
        if item_priority not in allowed_priority:
            item_priority = fallback_priority

        item_phase = item.get("phase")
        if item_phase not in allowed_phase:
            item_phase = fallback_phase

        normalized.append(
            {
                "title": item_title,
                "description": item_desc,
                "priority": item_priority,
                "phase": item_phase,
            }
        )

    if len(normalized) < 2:
        return []

    return normalized[:max_parts]


def _normalize_project_tags(raw_tags: dict | list | None, fallback: dict | None = None) -> dict[str, bool]:
    tags = {k: False for k in _TAG_KEYS}

    if isinstance(fallback, dict):
        for key in _TAG_KEYS:
            if key in fallback:
                tags[key] = bool(fallback[key])

    if isinstance(raw_tags, dict):
        for key in _TAG_KEYS:
            if key in raw_tags:
                tags[key] = bool(raw_tags[key])
    elif isinstance(raw_tags, list):
        for key in raw_tags:
            if key in tags:
                tags[key] = True

    # Canonical constraints:
    # - is_full_stack is derived.
    # - is_script is only true for standalone script/CLI projects (no FE/BE).
    tags["is_full_stack"] = tags["has_frontend"] and tags["has_backend"]
    if tags["has_frontend"] or tags["has_backend"]:
        tags["is_script"] = False
    return tags


def _minimum_ticket_count(tags: dict[str, bool]) -> int:
    if tags.get("is_script"):
        return 1
    if tags.get("has_frontend") and tags.get("has_backend"):
        return 7
    if tags.get("has_frontend") or tags.get("has_backend") or tags.get("is_mobile_app") or tags.get("is_devops_program"):
        return 4
    return 3


def _needs_ticket_rebalance(tickets_payload: dict, tags: dict[str, bool]) -> bool:
    tickets = tickets_payload.get("tickets") if isinstance(tickets_payload, dict) else None
    if not isinstance(tickets, list) or not tickets:
        return False

    ticket_count = len(tickets)
    longest_description = max(len((t.get("description") or "").strip()) for t in tickets)
    broad_ticket_found = any(
        _OVERSIZED_TICKET_RE.search(
            f"{t.get('title', '')} {(t.get('description', '') or '')[:300]}"
        )
        for t in tickets
    )

    if tags.get("is_script"):
        return longest_description > 1600 or (ticket_count == 1 and longest_description > 900)

    return (
        ticket_count < _minimum_ticket_count(tags)
        or longest_description > _OVERSIZED_DESCRIPTION_CHARS
        or (broad_ticket_found and ticket_count <= 5)
    )


def _rebalance_ticket_payload(original_payload: dict) -> dict | None:
    prompt = (
        "Rebalance this ticket plan into smaller, token-safe tickets.\n"
        "Do not reduce quality; increase ticket granularity where needed.\n\n"
        "Original ticket payload:\n"
        f"```json\n{json.dumps(original_payload, indent=2)}\n```"
    )

    response = _client.messages.create(
        model=_MODEL,
        max_tokens=8192,
        system=_TICKET_REBALANCE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    parsed = parse_agent_reply(response.content[0].text)
    rebalanced = parsed.get("tickets")
    if isinstance(rebalanced, dict) and isinstance(rebalanced.get("tickets"), list) and rebalanced.get("tickets"):
        return rebalanced
    return None


def _normalize_ticket_type(value: str | None) -> str:
    lowered = (value or "").strip().lower()
    return lowered if lowered in _ALLOWED_TICKET_TYPES else ""


def _coerce_ticket_types_for_project(
    tickets_payload: dict,
    tags: dict[str, bool],
) -> None:
    ticket_rows = tickets_payload.get("tickets")
    if not isinstance(ticket_rows, list):
        return

    force_script_type = bool(tags.get("is_script")) and not (
        tags.get("has_frontend") or tags.get("has_backend")
    )

    for ticket in ticket_rows:
        if not isinstance(ticket, dict):
            continue

        normalized_type = _normalize_ticket_type(ticket.get("type"))
        if force_script_type:
            normalized_type = "script"
        if not normalized_type:
            normalized_type = "backend"

        ticket["type"] = normalized_type

        labels = list(ticket.get("labels") or [])
        if normalized_type not in labels:
            labels.insert(0, normalized_type)
        for key, enabled in tags.items():
            if enabled and key not in labels:
                labels.append(key)
        ticket["labels"] = labels


def _enforce_fullstack_backend_handoff(
    tickets_payload: dict,
    tags: dict[str, bool],
) -> None:
    """
    Ensure frontend tickets run after backend tickets for full-stack projects.

    This creates a deterministic backend -> frontend handoff by making each
    frontend ticket depend on the last backend ticket when needed.
    """
    if not (tags.get("has_frontend") and tags.get("has_backend")):
        return

    ticket_rows = tickets_payload.get("tickets")
    if not isinstance(ticket_rows, list) or not ticket_rows:
        return

    backend_rows = [t for t in ticket_rows if isinstance(t, dict) and t.get("type") == "backend"]
    frontend_rows = [t for t in ticket_rows if isinstance(t, dict) and t.get("type") == "frontend"]
    if not backend_rows or not frontend_rows:
        return

    def _seq_value(ticket: dict) -> int:
        try:
            return int(ticket.get("sequence") or 0)
        except (TypeError, ValueError):
            return 0

    last_backend = max(
        backend_rows,
        key=lambda t: (_seq_value(t), str(t.get("id", ""))),
    )
    last_backend_id = str(last_backend.get("id") or "").strip()
    last_backend_seq = _seq_value(last_backend)
    if not last_backend_id:
        return

    for ticket in frontend_rows:
        deps = [str(dep).strip() for dep in (ticket.get("dependsOn") or []) if str(dep).strip()]
        if last_backend_id not in deps:
            deps.append(last_backend_id)
        ticket["dependsOn"] = list(dict.fromkeys(deps))

        seq = _seq_value(ticket)
        if seq <= last_backend_seq:
            ticket["sequence"] = last_backend_seq + 1


def normalize_tasking_payload_for_storage(
    tickets_payload: dict | None,
    project_tags: dict | None = None,
) -> dict | None:
    """
    Normalize PM tasking payload so downstream storage/routing is deterministic.

    - Ensures projectTags is complete and derived fields are correct.
    - Coerces ticket types for script projects.
    - Ensures each ticket has its final type and true project tags in labels.
    """
    if not isinstance(tickets_payload, dict):
        return None

    normalized_tags = _normalize_project_tags(
        tickets_payload.get("projectTags"),
        project_tags if isinstance(project_tags, dict) else None,
    )
    tickets_payload["projectTags"] = normalized_tags
    _coerce_ticket_types_for_project(tickets_payload, normalized_tags)
    _enforce_fullstack_backend_handoff(tickets_payload, normalized_tags)
    return tickets_payload


# ─── LLM caller ───────────────────────────────────────────────────────────────

def _call_llm(history: list[dict], max_tokens: int = 512) -> str:
    """
    Sends the conversation history to Claude and returns the raw reply text.

    history format (Anthropic SDK):
        [{"role": "user" | "assistant", "content": "..."}]
    """
    response = _client.messages.create(
        model=_MODEL,
        max_tokens=max_tokens,
        system=PM_SYSTEM_PROMPT,
        messages=history,
    )
    return response.content[0].text


# ─── Public API used by routes ────────────────────────────────────────────────

def get_initial_message(idea_text: str) -> str:
    """
    Called once when a conversation is created.
    Sends the user's opening idea to Claude and returns the PM's first reply.
    """
    history = [{"role": "user", "content": idea_text}]
    raw = _call_llm(history)
    result = parse_agent_reply(raw)
    return result["displayText"]


def summarize_idea(idea_text: str) -> str:
    """
    Generate a short PM-style summary suitable for idea card headers.
    Falls back to a cleaned/truncated user prompt when the LLM fails.
    """
    cleaned_idea = _strip_project_type_prefix(idea_text)
    if not cleaned_idea:
        cleaned_idea = (idea_text or "").strip()

    if not cleaned_idea:
        return "Project idea"

    try:
        response = _client.messages.create(
            model=_MODEL,
            max_tokens=128,
            system=_IDEA_SUMMARY_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": cleaned_idea}],
        )
        summary = (response.content[0].text or "").strip().strip('"').strip("'")
        summary = re.sub(r"\s+", " ", summary).strip()
        if summary:
            return summary[:255]
    except Exception as exc:
        logger.warning("summarize_idea failed, using fallback: %s", exc)

    if len(cleaned_idea) > 200:
        return f"{cleaned_idea[:197].rstrip()}..."
    return cleaned_idea


def get_pm_response(
    history: list[dict],
    user_message_count: int,
) -> tuple[str, bool, dict | None, dict]:
    """
    Called every time the user sends a follow-up message.

    history            — full conversation so far (role/content dicts, newest last).
    user_message_count — total user messages including the one just sent.

    Returns: (display_text, is_ready, tickets_or_None)
    """
    raw = _call_llm(history)
    result = parse_agent_reply(raw)
    switch_meta = {
        "asked_user_change_product_type": bool(result.get("askedUserChangeProductType", False)),
        "requested_project_type": result.get("requestedProjectType"),
    }
    return result["displayText"], result["isReady"], result["tickets"], switch_meta


async def run_tasking(
    history: list[dict],
) -> dict:
    """
    Calls the LLM with the "Start Tasking" trigger and returns the parsed result.

    Returns:
        {
          "agent_reply": str,         # raw display text (not stored in DB directly)
          "tickets": dict | None,     # full parsed ticket payload from the LLM
          "projectTags": dict | None, # normalized project type tags
        }

    GitHub repo creation, Jira project creation, and Jira ticket pushing are
    handled by the caller (the conversations route) so the order can be
    enforced: create project → push tickets.
    """
    tasking_history = history + [{"role": "user", "content": TASKING_ACTION_MESSAGE}]
    raw    = _call_llm(tasking_history, max_tokens=4096)
    parsed = parse_agent_reply(raw)

    # Recovery: if JSON was malformed/missing, ask once for strict JSON-only retry.
    if parsed.get("tickets") is None:
        logger.warning(
            "run_tasking: first pass did not return parseable ticket JSON. Retrying once."
        )
        retry_history = tasking_history + [{
            "role": "user",
            "content": (
                "Your previous response was malformed or incomplete. "
                "Return ONLY the complete ticket JSON object in a ```json fenced block."
            ),
        }]
        retry_raw = _call_llm(retry_history, max_tokens=6144)
        retry_parsed = parse_agent_reply(retry_raw)
        if retry_parsed.get("tickets") is not None:
            parsed = retry_parsed

    if parsed.get("tickets") is None:
        logger.warning(
            "run_tasking: LLM response did not contain parseable ticket JSON. "
            "Raw output (first 500 chars): %s", raw[:500]
        )

    tickets_payload = parsed.get("tickets")
    if isinstance(tickets_payload, dict):
        normalized_tags = _normalize_project_tags(
            tickets_payload.get("projectTags"),
            parsed.get("projectTags"),
        )

        if _needs_ticket_rebalance(tickets_payload, normalized_tags):
            logger.info(
                "run_tasking: ticket plan appears too coarse (count=%d). Rebalancing.",
                len(tickets_payload.get("tickets", [])),
            )
            rebalanced = _rebalance_ticket_payload(tickets_payload)
            if rebalanced is not None:
                parsed["tickets"] = rebalanced
                parsed["projectTags"] = _normalize_project_tags(
                    rebalanced.get("projectTags"), normalized_tags
                )
                logger.info(
                    "run_tasking: rebalanced ticket count %d -> %d.",
                    len(tickets_payload.get("tickets", [])),
                    len(rebalanced.get("tickets", [])),
                )
            else:
                logger.warning(
                    "run_tasking: ticket rebalancing failed parse; keeping original plan."
                )
                parsed["projectTags"] = normalized_tags
        else:
            parsed["projectTags"] = normalized_tags

        final_payload = parsed.get("tickets")
        final_tags = parsed.get("projectTags") or normalized_tags
        normalized_payload = normalize_tasking_payload_for_storage(final_payload, final_tags)
        if isinstance(normalized_payload, dict):
            parsed["tickets"] = normalized_payload
            parsed["projectTags"] = normalized_payload.get("projectTags", final_tags)

    return {
        "agent_reply": parsed["displayText"],
        "tickets":     parsed.get("tickets"),
        "projectTags": parsed.get("projectTags"),
    }


# ─── README generation ────────────────────────────────────────────────────────

_README_SYSTEM_PROMPT = """
You are the PM agent at AI Factory. Your task is to write a professional,
well-structured README.md for a project that was just built by AI developer agents.

Use the conversation history provided to understand what the project does, its
features, and its tech stack. Write the README in Markdown.

Use the provided implementation handoff and repository file tree as the source
of truth for concrete commands and file paths.

Include these sections (skip any that don't apply):

1. **Project title** — as an H1
2. **Description** — 2-3 sentences explaining what the project is and who it's for
3. **Live Demo** — if a live URL is provided, include it as a clickable link here
4. **Features** — bullet list of key features
5. **Tech Stack** — backend and frontend technologies used
6. **Getting Started**
   - Prerequisites
   - Installation steps for backend and frontend
   - Environment variables needed (use placeholder values)
   - How to run the project locally
7. **Project Structure** — brief overview of the folder layout
8. **API Endpoints** — table of key endpoints if it's a web app (method, path, description)
9. **License** — default to MIT

Script/CLI-specific requirements:
- If the project tags indicate `is_script: true`, include a dedicated **Run the Script** section.
- In that section provide exact commands for:
    - Windows PowerShell
    - macOS/Linux shell
- Include at least one real usage example (with arguments if relevant) and expected output behavior.
- If executable packaging is part of scope, add a **Build Executable** section describing how to produce and where to find the `.exe` artifact.

Accuracy rules:
- Never reference files/commands that are not present in the repository file tree context.
- Never use placeholder filenames (like `main.py`) unless that file exists in the repository.
- If implementation handoff and conversation conflict, prefer implementation handoff for technical details.

Keep it concise and practical. Output ONLY the raw Markdown — no code fences
wrapping the entire document, no preamble, no explanation.
"""


_CLAUDE_MD_SYSTEM_PROMPT = """
You are the PM agent at AI Factory. Your task is to write a comprehensive CLAUDE.md file
for a project that was just built entirely by AI developer agents. This file will be read
by future AI agents (Claude Code or similar) who need to work on, debug, or extend this
codebase. Write it as if briefing a highly capable developer who has never seen this repo.

Write the CLAUDE.md in Markdown. Be specific, technical, and structured. Include:

1. **Project Overview** — What the project does, who it serves, and the core problem it solves (2–4 sentences).
2. **Tech Stack** — Every technology, framework, library, and tool used. Separate Backend and Frontend clearly.
3. **Architecture** — How the system is structured. Describe the folder layout, entry points, and how the backend and frontend communicate (REST, WebSocket, etc.).
4. **Build & Development Commands** — Exact commands to install dependencies, run the dev server, and build for production — for both backend and frontend.
5. **Environment Variables** — Every required env var, its purpose, and a placeholder value. Use a code block.
6. **API Endpoints** — A Markdown table of all backend routes: Method | Path | Description | Auth Required.
7. **Database Schema** — Every model/collection, its key fields, field types, and relationships to other models.
8. **Key Algorithms & Patterns** — Any non-trivial logic worth flagging: auth flows, data processing pipelines, sequencing logic, state machines, caching strategies.
9. **What Was Built (Tickets)** — A breakdown of every implemented ticket grouped by Phase (Foundation → Core → Integration → Polish). For each ticket: ID, title, and a one-line summary of what it added to the codebase.
10. **Known Constraints & Notes** — Decisions made, trade-offs, or gotchas a future agent must know before touching this code.

Output ONLY raw Markdown — no code fences wrapping the entire document, no preamble, no explanation.
"""


def generate_claude_md(
    history: list[dict],
    tickets: list[dict],
    project_name: str = "Project",
    live_url: str | None = None,
) -> str:
    """
    Generate a CLAUDE.md from the PM conversation history and the full ticket list.
    Committed to the generated project repo so future AI agents have full context.

    Args:
        history:      PM conversation messages (role/content dicts).
        tickets:      List of ticket dicts with keys: id, type, phase, sequence,
                      title, description, status.
        project_name: Human-friendly project title derived from the repo slug.
        live_url:     Optional GitHub Pages URL for reference.

    Returns the raw Markdown string ready to be committed to the repo.
    """
    live_url_line = f"The project is live at: {live_url}\n\n" if live_url else ""

    # Format the ticket list into a structured block so the LLM has exact data
    ticket_lines = []
    for t in sorted(tickets, key=lambda x: (x.get("sequence") or 999, x.get("id", ""))):
        phase = t.get("phase") or "Unknown"
        ticket_lines.append(
            f"[{t.get('id', '?')}] ({t.get('type', '?').upper()} | {phase} | seq {t.get('sequence', '?')}) "
            f"{t.get('title', 'Untitled')} — {t.get('description', '')[:200]}"
        )
    tickets_block = "\n".join(ticket_lines)

    claude_md_prompt = (
        f"The project is called \"{project_name}\".\n\n"
        f"{live_url_line}"
        f"The following tickets were implemented by AI developer agents to build this project:\n\n"
        f"{tickets_block}\n\n"
        "Using the conversation history above and the ticket list, write a complete CLAUDE.md "
        "for this repository. Be precise about the tech stack, file structure, and what each "
        "ticket added to the codebase. Future AI agents will rely on this file to understand "
        "the project without reading every source file."
    )
    messages = history + [{"role": "user", "content": claude_md_prompt}]

    response = _client.messages.create(
        model=_MODEL,
        max_tokens=4096,
        system=_CLAUDE_MD_SYSTEM_PROMPT,
        messages=messages,
    )
    return response.content[0].text


def generate_readme(
    history: list[dict],
    project_name: str = "Project",
    live_url: str | None = None,
    project_tags: dict | None = None,
    repo_files: list[str] | None = None,
    implementation_handoff: list[dict] | None = None,
) -> str:
    """
    Generate a README.md from the PM conversation history.

    Args:
        history:      PM conversation messages (role/content dicts).
        project_name: Human-friendly project title derived from the repo slug.
        live_url:     Optional GitHub Pages URL to embed in the Live Demo section.
        project_tags: Normalized project tags dict from conversation metadata.
        repo_files:   Repository file tree from main branch.
        implementation_handoff: Ticket-level summaries and generated file lists.

    Returns the raw Markdown string ready to be committed to the repo.
    """
    def _normalize_repo_path(path: str) -> str:
        return (path or "").replace("\\", "/").strip("/").lower()

    def _build_readme_handoff_context() -> str:
        sections: list[str] = []

        safe_repo_files = [
            str(path).replace("\\", "/").strip("/")
            for path in (repo_files or [])
            if path
        ]
        if safe_repo_files:
            file_lines = "\n".join(f"- {path}" for path in safe_repo_files[:220])
            sections.append(
                "Repository files currently on main branch (source of truth):\n"
                f"{file_lines}"
            )

        if implementation_handoff:
            handoff_lines: list[str] = []
            for row in implementation_handoff[:40]:
                if not isinstance(row, dict):
                    continue
                ticket_id = row.get("id", "?")
                title = str(row.get("title", "Untitled")).strip()
                status = row.get("status", "unknown")
                summary = str(row.get("summary", "")).strip()
                notes = str(row.get("notes", "")).strip()
                files = [
                    str(path).replace("\\", "/").strip("/")
                    for path in (row.get("generated_files") or [])[:10]
                    if path
                ]

                line = f"- [{ticket_id}] {title} (status: {status})"
                if summary:
                    line += f" | summary: {summary[:180]}"
                if files:
                    line += f" | files: {', '.join(files)}"
                if notes:
                    line += f" | notes: {notes[:160]}"
                handoff_lines.append(line)

            if handoff_lines:
                sections.append(
                    "Developer agent implementation handoff:\n"
                    + "\n".join(handoff_lines)
                )

        if not sections:
            return "Implementation handoff is unavailable. Prefer conservative, generic setup instructions."
        return "\n\n".join(sections)

    def _detect_script_entrypoint() -> str | None:
        safe_repo_files = [
            str(path).replace("\\", "/").strip("/")
            for path in (repo_files or [])
            if path
        ]
        py_candidates = [
            path for path in safe_repo_files
            if path.lower().endswith(".py")
            and not path.lower().startswith("tests/")
            and not path.lower().startswith("test/")
            and not path.lower().startswith(".github/")
            and "__pycache__" not in path.lower()
            and not path.lower().endswith("_test.py")
        ]
        if not py_candidates:
            return None

        hinted_basenames: set[str] = set()
        for row in implementation_handoff or []:
            if not isinstance(row, dict):
                continue
            for path in row.get("generated_files") or []:
                safe = str(path).replace("\\", "/").strip("/")
                if safe.lower().endswith(".py"):
                    hinted_basenames.add(os.path.basename(safe).lower())

        preferred_names = {"main.py", "run.py", "app.py", "cli.py", "__main__.py"}

        ranked = sorted(
            py_candidates,
            key=lambda path: (
                0 if os.path.basename(path).lower() in hinted_basenames else 1,
                path.count("/"),
                0 if os.path.basename(path).lower() in preferred_names else 1,
                len(path),
                path.lower(),
            ),
        )
        return ranked[0]

    def _correct_script_readme_commands(readme_md: str, entrypoint: str | None) -> str:
        if not tags.get("is_script"):
            return readme_md

        safe_repo_files = [
            str(path).replace("\\", "/").strip("/")
            for path in (repo_files or [])
            if path
        ]
        known_py_paths = {
            _normalize_repo_path(path)
            for path in safe_repo_files
            if path.lower().endswith(".py")
        }
        basename_counts: dict[str, int] = {}
        basename_to_path: dict[str, str] = {}
        for path in known_py_paths:
            base = os.path.basename(path)
            basename_counts[base] = basename_counts.get(base, 0) + 1
            if base not in basename_to_path:
                basename_to_path[base] = path

        if not known_py_paths:
            return readme_md

        cmd_pattern = re.compile(
            r"(?P<prefix>\b(?:py|python|python3)\b\s+)(?P<script>[^\s`\"']+\.py)\b",
            re.IGNORECASE,
        )

        def _replace_cmd(match: re.Match) -> str:
            script = _normalize_repo_path(match.group("script"))
            if script in known_py_paths:
                return match.group(0)

            base = os.path.basename(script)
            if base in basename_to_path and basename_counts.get(base, 0) == 1:
                return f"{match.group('prefix')}{basename_to_path[base]}"

            if entrypoint:
                return f"{match.group('prefix')}{entrypoint}"
            return match.group(0)

        corrected = cmd_pattern.sub(_replace_cmd, readme_md)

        if entrypoint:
            entry_basename = re.escape(os.path.basename(entrypoint))
            has_entry_command = re.search(
                rf"\b(?:py|python|python3)\b\s+[^\n`]*{entry_basename}\b",
                corrected,
                re.IGNORECASE,
            )
            if not has_entry_command:
                corrected = corrected.rstrip() + (
                    "\n\n## Run the Script\n\n"
                    "Windows PowerShell:\n"
                    "```powershell\n"
                    f"py {entrypoint}\n"
                    "```\n\n"
                    "macOS/Linux:\n"
                    "```bash\n"
                    f"python {entrypoint}\n"
                    "```\n"
                )

        return corrected

    tags = project_tags if isinstance(project_tags, dict) else {}
    tags_json = json.dumps(tags, sort_keys=True)
    handoff_context = _build_readme_handoff_context()
    script_entrypoint = _detect_script_entrypoint() if tags.get("is_script") else None
    script_entrypoint_hint = (
        f"Detected primary runnable script file: {script_entrypoint}\n"
        "Use this file for run/build commands unless a different launcher is explicitly present in the repository tree.\n\n"
        if script_entrypoint
        else ""
    )

    live_url_line = (
        f"The project is deployed and live at: {live_url}\n"
        "Include this URL in the Live Demo section.\n\n"
        if live_url
        else ""
    )
    deployment_context_line = (
        "The project has already been built and deployed. "
        if live_url
        else "The project has already been built and is ready to run locally. "
    )
    readme_prompt = (
        f"The project is called \"{project_name}\".\n\n"
        f"Project tags (JSON): {tags_json}\n\n"
        f"{live_url_line}"
        f"{script_entrypoint_hint}"
        "Implementation handoff context:\n"
        f"{handoff_context}\n\n"
        "Based on the conversation history above, write a README.md for this project.\n"
        f"{deployment_context_line}Write the README as if it "
        "is being added to the repository root."
    )
    messages = history + [{"role": "user", "content": readme_prompt}]

    response = _client.messages.create(
        model=_MODEL,
        max_tokens=4096,
        system=_README_SYSTEM_PROMPT,
        messages=messages,
    )

    readme_md = response.content[0].text
    readme_md = _correct_script_readme_commands(readme_md, script_entrypoint)
    return readme_md
