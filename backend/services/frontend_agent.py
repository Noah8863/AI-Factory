"""
services/frontend_agent.py
──────────────────────────
Calls the Frontend Developer AI agent for a single Jira ticket and writes
the generated files to the target GitHub repository.
"""

import logging
import os

import anthropic

from agents.frontend_agent import FRONTEND_SYSTEM_PROMPT, parse_developer_output
from services.github_service import write_file_to_repo

logger = logging.getLogger(__name__)

_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

# Default tech stack injected into the system prompt.
_TECH_STACK = os.getenv(
    "FRONTEND_TECH_STACK",
    "React 18, Vite, SCSS modules, Tailwind CSS (utility classes), Axios, React Router v6, Material Icons",
)


async def run_frontend_task(
    ticket,          # models.ticket.Ticket ORM instance
    ticket_prompt: str,
    repo_name: str,
) -> dict:
    """
    Call the Frontend Developer agent with a ticket, parse its JSON output,
    write the generated files to the GitHub repo, and return a result dict.

    Result dict shape:
        {
            "summary":       str,
            "files":         [{"path": str, "content": str, "action": str}, ...],
            "notes":         str | None,
            "files_written": int,
        }

    Raises on unrecoverable errors (caller marks ticket as failed).
    """
    system_msg = FRONTEND_SYSTEM_PROMPT.format(tech_stack=_TECH_STACK)

    logger.info(
        "Calling frontend agent for ticket %s: %s",
        ticket.ticket_id, ticket.title,
    )

    response = _client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8000,
        system=system_msg,
        messages=[{"role": "user", "content": ticket_prompt}],
    )

    raw = response.content[0].text
    logger.debug(
        "Frontend agent raw output for ticket %s (%d chars).",
        ticket.ticket_id, len(raw),
    )

    result = parse_developer_output(raw)

    # ── Write files to GitHub ─────────────────────────────────────────────────
    files_written = 0
    if repo_name:
        for f in result.get("files", []):
            path    = f.get("path", "").strip("/")
            content = f.get("content", "")
            if not path or not content:
                continue
            ok = write_file_to_repo(
                repo_name=repo_name,
                file_path=path,
                content=content,
                branch="main",
                commit_message=f"AI Frontend Dev [{ticket.ticket_id}]: {path}",
            )
            if ok:
                files_written += 1
                logger.info("Wrote %s → %s", path, repo_name)
            else:
                logger.warning("Failed to write %s → %s", path, repo_name)
    else:
        logger.warning(
            "No repo_name for ticket %s — skipping GitHub write.", ticket.ticket_id
        )

    result["files_written"] = files_written
    return result
