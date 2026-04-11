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

from dotenv import load_dotenv
import anthropic
from sqlalchemy.orm import Session

from agents.pm_agent import PM_SYSTEM_PROMPT, parse_agent_reply
from services.jira_service import push_tickets_to_jira, JiraServiceError

load_dotenv()

logger = logging.getLogger(__name__)

_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
_MODEL  = "claude-sonnet-4-20250514"

# The exact message the route sends (and the system prompt expects) to trigger
# ticket generation.  Defined here so routes and tests can import it.
TASKING_ACTION_MESSAGE = "ACTION: Start tasking. Generate the Jira tickets now."


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


def get_pm_response(
    history: list[dict],
    user_message_count: int,
) -> tuple[str, bool, dict | None]:
    """
    Called every time the user sends a follow-up message.

    history            — full conversation so far (role/content dicts, newest last).
    user_message_count — total user messages including the one just sent.

    Returns: (display_text, is_ready, tickets_or_None)
    """
    raw = _call_llm(history)
    result = parse_agent_reply(raw)
    return result["displayText"], result["isReady"], result["tickets"]


async def run_tasking(
    history:  list[dict],
    user_id:  int | None,
    db:       Session | None,
) -> dict:
    """
    Orchestrates the full "Start Tasking" flow:

    1. Appends the standard action message to the conversation history.
    2. Calls the LLM and parses the resulting ticket JSON.
    3. If user_id and db are provided (i.e. the user is authenticated) and
       the user has a connected Jira account, pushes every ticket to Jira.
    4. Returns a result dict:
       {
         "agent_reply":          str,         # raw text to store as agent message
         "tickets":              dict | None, # parsed ticket payload from LLM
         "jira_tickets_created": list[dict],  # [] when Jira not connected
         "jira_error":           str | None,  # human-readable error if Jira push failed
       }
    """
    # ── 1. Build history including the trigger message ────────────
    tasking_history = history + [{"role": "user", "content": TASKING_ACTION_MESSAGE}]

    # ── 2. Call LLM — use a high token limit so the full JSON is never truncated
    raw    = _call_llm(tasking_history, max_tokens=4096)
    parsed = parse_agent_reply(raw)

    agent_reply = parsed["displayText"]
    tickets     = parsed.get("tickets")  # dict with "tickets" list, or None

    if tickets is None:
        logger.warning(
            "run_tasking: LLM response did not contain parseable ticket JSON. "
            "Raw output (first 500 chars): %s", raw[:500]
        )

    # ── 3. Push to Jira if possible ───────────────────────────────
    jira_results: list[dict] = []
    jira_error:   str | None = None

    if tickets and user_id is not None and db is not None:
        ticket_list = tickets.get("tickets", [])
        if ticket_list:
            try:
                raw_results = await push_tickets_to_jira(
                    user_id=user_id,
                    db=db,
                    tickets=ticket_list,
                )
                # Separate successfully created tickets from per-ticket API errors
                jira_results = [r for r in raw_results if "key" in r]
                failed       = [r for r in raw_results if "error" in r]

                if jira_results:
                    logger.info(
                        "%d Jira ticket(s) created for user %s.",
                        len(jira_results),
                        user_id,
                    )
                if failed:
                    titles = ", ".join(f["title"] for f in failed)
                    first_err = failed[0].get("error", "unknown error")
                    jira_error = (
                        f"{len(failed)} ticket(s) failed to create ({titles}). "
                        f"Jira API error: {first_err}"
                    )
                    logger.warning(
                        "Jira ticket creation partial failure for user %s: %s",
                        user_id,
                        jira_error,
                    )
            except JiraServiceError as exc:
                jira_error = str(exc)
                logger.warning(
                    "Jira ticket creation failed for user %s: %s",
                    user_id,
                    exc,
                )

    return {
        "agent_reply":          agent_reply,
        "tickets":              tickets,
        "jira_tickets_created": jira_results,
        "jira_error":           jira_error,
    }
