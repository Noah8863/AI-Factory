"""
services/pm_agent.py
--------------------
I/O layer for the PM agent.
Reads ANTHROPIC_API_KEY from the backend .env file.
The system prompt and parser live in agents/pm_agent.py and are
never exposed to the frontend or to any client-side code.
"""

import os
from dotenv import load_dotenv
import anthropic

from agents.pm_agent import PM_SYSTEM_PROMPT, parse_agent_reply

load_dotenv()

_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
_MODEL  = "claude-sonnet-4-20250514"


# ─── LLM caller ───────────────────────────────────────────────────────────────

def _call_llm(history: list[dict]) -> str:
    """
    Sends the conversation history to Claude and returns the raw reply text.

    history format (Anthropic SDK):
        [{"role": "user" | "assistant", "content": "..."}]
    """
    response = _client.messages.create(
        model=_MODEL,
        max_tokens=1024,
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
