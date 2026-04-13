"""
services/script_agent.py
------------------------
Calls the Script Developer AI agent for a single Jira ticket and writes
generated files directly to the main branch of the target GitHub repository.
"""

import asyncio
import logging
import os

import anthropic

from agents.script_agent import SCRIPT_SYSTEM_PROMPT, parse_developer_output
from services.github_service import write_file_to_repo

logger = logging.getLogger(__name__)

_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

_TECH_STACK = os.getenv(
    "SCRIPT_TECH_STACK",
    "Python 3.11+, Bash/Shell scripting, YAML/JSON automation config, TypeScript for tooling",
)


async def run_script_task(
    ticket,
    ticket_prompt: str,
    repo_name: str,
) -> dict:
    """
    Call the Script Developer agent with a ticket, parse its JSON output,
    write generated files directly to main on GitHub, and return a result dict.
    """
    system_msg = SCRIPT_SYSTEM_PROMPT.format(tech_stack=_TECH_STACK)

    logger.info(
        "Calling script agent for ticket %s: %s",
        ticket.ticket_id, ticket.title,
    )

    async def _call_script_model(prompt: str):
        return await asyncio.to_thread(
            _client.messages.create,
            model="claude-sonnet-4-6",
            max_tokens=16384,
            system=system_msg,
            messages=[{"role": "user", "content": prompt}],
        )

    try:
        response = await _call_script_model(ticket_prompt)
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
        "Script agent response for ticket %s: %d chars, stop_reason=%s",
        ticket.ticket_id, len(raw), stop_reason,
    )

    result = parse_developer_output(raw)

    if stop_reason == "max_tokens" and not result.get("files"):
        logger.warning(
            "Script agent output truncated with no parseable files for ticket %s; retrying in recovery mode.",
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
            recovery_response = await _call_script_model(recovery_prompt)
            raw = recovery_response.content[0].text
            stop_reason = recovery_response.stop_reason
            result = parse_developer_output(raw)
            logger.info(
                "Script recovery response for ticket %s: %d chars, stop_reason=%s",
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
            f"Script agent response truncated (hit max_tokens) for ticket "
            f"{ticket.ticket_id} even after recovery retry. Output was {len(raw)} chars."
        )
    if stop_reason == "max_tokens" and result.get("files"):
        logger.warning(
            "Script ticket %s hit max_tokens but returned parseable files; proceeding.",
            ticket.ticket_id,
        )

    if not result.get("files"):
        logger.warning(
            "Script agent returned no files for ticket %s. Raw output (first 500 chars): %s",
            ticket.ticket_id, raw[:500],
        )
        result["parse_warning"] = (
            "Agent returned no actionable files. "
            f"Raw output preview: {raw[:300]}{'...' if len(raw) > 300 else ''}"
        )

    files_written = 0
    file_errors = []

    if repo_name:
        for f in result.get("files", []):
            path = f.get("path", "").replace("\\", "/").strip("/")
            content = f.get("content", "")
            if not path or not content:
                file_errors.append({"path": path or "(empty)", "error": "Missing path or content"})
                continue

            if path.startswith("../") or "/../" in f"/{path}":
                file_errors.append({"path": path, "error": "Path traversal is not allowed"})
                continue

            try:
                summary = result.get("summary", ticket.title)
                ok = await asyncio.to_thread(
                    write_file_to_repo,
                    repo_name=repo_name,
                    file_path=path,
                    content=content,
                    branch="main",
                    commit_message=f"AI Agent: [{ticket.ticket_id}] {summary} - {path}",
                )
                if ok:
                    files_written += 1
                    logger.info("Wrote %s -> %s (main)", path, repo_name)
                else:
                    file_errors.append({"path": path, "error": "GitHub API returned non-success status"})
                    logger.warning("Failed to write %s -> %s", path, repo_name)
            except Exception as exc:
                file_errors.append({"path": path, "error": f"{type(exc).__name__}: {exc}"})
                logger.warning("Exception writing %s -> %s: %s", path, repo_name, exc)
    else:
        logger.warning(
            "No repo_name for ticket %s - skipping GitHub write.", ticket.ticket_id
        )

    expected_files = len(result.get("files", []))
    if expected_files == 0:
        raise RuntimeError(
            f"Script agent produced no files for ticket {ticket.ticket_id}. "
            f"The LLM response could not be parsed into actionable code. "
            f"Raw output preview: {raw[:400]}"
        )
    if files_written == 0:
        raise RuntimeError(
            f"Script agent generated {expected_files} file(s) for ticket "
            f"{ticket.ticket_id} but all GitHub writes failed. "
            f"Errors: {file_errors}"
        )

    result["files_written"] = files_written
    result["file_errors"] = file_errors
    result["branch"] = "main"

    return result
