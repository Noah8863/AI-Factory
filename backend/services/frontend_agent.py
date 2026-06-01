"""
services/frontend_agent.py
──────────────────────────
Calls the Frontend Developer AI agent for a single Jira ticket and writes
the generated files directly to the main branch of the target GitHub repository.
"""

import asyncio
import logging
import os
import re

import anthropic

from agents.frontend_agent import FRONTEND_SYSTEM_PROMPT, parse_developer_output
from services.github_service import write_file_to_repo

logger = logging.getLogger(__name__)

_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

# Default tech stack injected into the system prompt.
_TECH_STACK = os.getenv(
    "FRONTEND_TECH_STACK",
    "Vanilla JavaScript (ES6+), HTML5, CSS3, Fetch API for HTTP requests",
)


def _find_placeholder_signals(ticket_prompt: str, result: dict) -> list[str]:
    """Detect placeholder/demo artifacts that are not requested by the ticket."""
    ticket_text = (ticket_prompt or "").lower()
    if "hello world" in ticket_text or "helloworld" in ticket_text:
        return []

    patterns: list[tuple[re.Pattern[str], str]] = [
        (re.compile(r"\bhello\s*world\b", re.IGNORECASE), "hello world literal"),
        (re.compile(r"\bhelloworld\b", re.IGNORECASE), "HelloWorld identifier"),
        (re.compile(r"/hello[-_]?world", re.IGNORECASE), "HelloWorld file path"),
    ]

    findings: list[str] = []
    for index, file_obj in enumerate(result.get("files", []) or []):
        path = str(file_obj.get("path", ""))
        content = str(file_obj.get("content", ""))

        for pattern, label in patterns:
            if pattern.search(path) or pattern.search(content):
                findings.append(f"{label} in {path or f'file[{index}]'}")
                break

    return findings


async def run_frontend_task(
    ticket,          # models.ticket.Ticket ORM instance
    ticket_prompt: str,
    repo_name: str,
    skip_ci_commits: bool = False,
) -> dict:
    """
    Call the Frontend Developer agent with a ticket, parse its JSON output,
    write the generated files directly to main on the GitHub repo, and return
    a result dict.

    Result dict shape:
        {
            "summary":       str,
            "files":         [{"path": str, "content": str, "action": str}, ...],
            "notes":         str | None,
            "files_written": int,
            "file_errors":   list,
            "branch":        "main",
        }

    Raises on unrecoverable errors (caller marks ticket as failed).
    """
    system_msg = FRONTEND_SYSTEM_PROMPT.replace("__TECH_STACK__", _TECH_STACK)

    logger.info(
        "Calling frontend agent for ticket %s: %s",
        ticket.ticket_id, ticket.title,
    )

    async def _call_frontend_model(prompt: str):
        return await asyncio.to_thread(
            _client.messages.create,
            model="claude-sonnet-4-6",
            max_tokens=16384,
            system=system_msg,
            messages=[{"role": "user", "content": prompt}],
        )

    # ── 1. Call LLM ───────────────────────────────────────────────────────────
    try:
        response = await _call_frontend_model(ticket_prompt)
    except anthropic.APIConnectionError as exc:
        raise RuntimeError(
            f"Anthropic API connection failed for ticket {ticket.ticket_id}: {exc}"
        ) from exc
    except anthropic.RateLimitError as exc:
        raise RuntimeError(
            f"Anthropic rate limit hit for ticket {ticket.ticket_id}. "
            f"Retry after a short wait. Details: {exc}"
        ) from exc
    except anthropic.APIStatusError as exc:
        raise RuntimeError(
            f"Anthropic API error ({exc.status_code}) for ticket {ticket.ticket_id}: "
            f"{exc.message}"
        ) from exc

    raw = response.content[0].text
    stop_reason = response.stop_reason
    logger.info(
        "Frontend agent response for ticket %s: %d chars, stop_reason=%s",
        ticket.ticket_id, len(raw), stop_reason,
    )

    # ── 2. Parse output ───────────────────────────────────────────────────────
    result = parse_developer_output(raw)

    if stop_reason == "max_tokens" and not result.get("files"):
        logger.warning(
            "Frontend agent output truncated with no parseable files for ticket %s; retrying in recovery mode.",
            ticket.ticket_id,
        )
        recovery_prompt = (
            f"{ticket_prompt}\n\n"
            "RECOVERY MODE: Your previous response was truncated by max_tokens. "
            "Return only a compact, minimum-viable implementation for this ticket. "
            "Prefer updating existing files. Limit output to essential files only. "
            "Respond with one valid JSON object exactly matching the required schema."
        )
        try:
            recovery_response = await _call_frontend_model(recovery_prompt)
            raw = recovery_response.content[0].text
            stop_reason = recovery_response.stop_reason
            result = parse_developer_output(raw)
            logger.info(
                "Frontend recovery response for ticket %s: %d chars, stop_reason=%s",
                ticket.ticket_id, len(raw), stop_reason,
            )
        except anthropic.APIConnectionError as exc:
            raise RuntimeError(
                f"Anthropic API connection failed during recovery for ticket {ticket.ticket_id}: {exc}"
            ) from exc
        except anthropic.RateLimitError as exc:
            raise RuntimeError(
                f"Anthropic rate limit hit during recovery for ticket {ticket.ticket_id}. "
                f"Retry after a short wait. Details: {exc}"
            ) from exc
        except anthropic.APIStatusError as exc:
            raise RuntimeError(
                f"Anthropic API error during recovery ({exc.status_code}) for ticket {ticket.ticket_id}: "
                f"{exc.message}"
            ) from exc

    if stop_reason == "max_tokens" and not result.get("files"):
        raise RuntimeError(
            f"Frontend agent response truncated (hit max_tokens) for ticket "
            f"{ticket.ticket_id} even after recovery retry. Output was {len(raw)} chars."
        )
    if stop_reason == "max_tokens" and result.get("files"):
        logger.warning(
            "Frontend ticket %s hit max_tokens but returned parseable files; proceeding.",
            ticket.ticket_id,
        )

    placeholder_findings = _find_placeholder_signals(ticket_prompt, result)
    if placeholder_findings:
        logger.warning(
            "Frontend agent output for ticket %s contained placeholder artifacts: %s. Retrying in quality recovery mode.",
            ticket.ticket_id,
            placeholder_findings,
        )
        quality_recovery_prompt = (
            f"{ticket_prompt}\n\n"
            "QUALITY RECOVERY MODE: Your previous response introduced placeholder/demo artifacts "
            f"that are not in the ticket requirements ({'; '.join(placeholder_findings[:5])}). "
            "Regenerate and remove all placeholder/demo code. Use meaningful domain-specific "
            "component/module names derived from the acceptance criteria. Do not create "
            "HelloWorld or demo-only files. Return one valid JSON object exactly matching "
            "the required schema."
        )

        try:
            recovery_response = await _call_frontend_model(quality_recovery_prompt)
            raw = recovery_response.content[0].text
            stop_reason = recovery_response.stop_reason
            result = parse_developer_output(raw)
            logger.info(
                "Frontend quality recovery response for ticket %s: %d chars, stop_reason=%s",
                ticket.ticket_id,
                len(raw),
                stop_reason,
            )
        except anthropic.APIConnectionError as exc:
            raise RuntimeError(
                f"Anthropic API connection failed during quality recovery for ticket {ticket.ticket_id}: {exc}"
            ) from exc
        except anthropic.RateLimitError as exc:
            raise RuntimeError(
                f"Anthropic rate limit hit during quality recovery for ticket {ticket.ticket_id}. "
                f"Retry after a short wait. Details: {exc}"
            ) from exc
        except anthropic.APIStatusError as exc:
            raise RuntimeError(
                f"Anthropic API error during quality recovery ({exc.status_code}) for ticket {ticket.ticket_id}: "
                f"{exc.message}"
            ) from exc

        placeholder_findings = _find_placeholder_signals(ticket_prompt, result)
        if placeholder_findings:
            raise RuntimeError(
                "Frontend agent output still contains placeholder/demo artifacts "
                f"for ticket {ticket.ticket_id} after quality recovery: {placeholder_findings}"
            )

    if not result.get("files"):
        logger.warning(
            "Frontend agent returned no files for ticket %s. Raw output (first 500 chars): %s",
            ticket.ticket_id, raw[:500],
        )
        result["parse_warning"] = (
            "Agent returned no actionable files. "
            f"Raw output preview: {raw[:300]}{'…' if len(raw) > 300 else ''}"
        )

    # ── 3. Write files directly to main branch ────────────────────────────────
    files_written = 0
    file_errors   = []

    if repo_name:
        for f in result.get("files", []):
            path    = f.get("path", "").strip("/")
            content = f.get("content", "")
            if not path or not content:
                file_errors.append({"path": path or "(empty)", "error": "Missing path or content"})
                continue

            # Guardrail: frontend files must live under frontend/
            if not path.startswith("frontend/"):
                path = f"frontend/{path}"

            try:
                summary = result.get("summary", ticket.title)
                commit_prefix = "[skip ci] " if skip_ci_commits else ""
                ok = await asyncio.to_thread(
                    write_file_to_repo,
                    repo_name=repo_name,
                    file_path=path,
                    content=content,
                    branch="main",
                    commit_message=f"{commit_prefix}AI Agent: [{ticket.ticket_id}] {summary} — {path}",
                )
                if ok:
                    files_written += 1
                    logger.info("Wrote %s → %s (main)", path, repo_name)
                else:
                    file_errors.append({"path": path, "error": "GitHub API returned non-success status"})
                    logger.warning("Failed to write %s → %s", path, repo_name)
            except Exception as exc:
                file_errors.append({"path": path, "error": f"{type(exc).__name__}: {exc}"})
                logger.warning("Exception writing %s → %s: %s", path, repo_name, exc)
    else:
        logger.warning(
            "No repo_name for ticket %s — skipping GitHub write.", ticket.ticket_id
        )

    # ── 4. Fail loudly if no files were actually pushed ───────────────────────
    expected_files = len(result.get("files", []))
    if expected_files == 0:
        raise RuntimeError(
            f"Frontend agent produced no files for ticket {ticket.ticket_id}. "
            f"The LLM response could not be parsed into actionable code. "
            f"Raw output preview: {raw[:400]}"
        )
    if files_written == 0:
        raise RuntimeError(
            f"Frontend agent generated {expected_files} file(s) for ticket "
            f"{ticket.ticket_id} but all GitHub writes failed. "
            f"Errors: {file_errors}"
        )

    result["files_written"] = files_written
    result["file_errors"]   = file_errors
    result["branch"]        = "main"

    return result
