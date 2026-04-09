"""
services/pm_agent.py
--------------------
I/O layer for the PM agent. This is the only file that should change
when wiring in a real LLM (e.g. the Claude API).

Routes call:
  get_initial_message(idea_text)          → str
  get_pm_response(history, user_count)    → (display_text, is_ready, tickets | None)

The system prompt and output parser live in agents/pm_agent.py and
are never exposed to the frontend or client-side code.
"""

from agents.pm_agent import PM_SYSTEM_PROMPT, parse_agent_reply  # noqa: F401

# ─── Canned stub responses ────────────────────────────────────────────────────
# These are returned until a real LLM client is wired in below.
# Each list entry corresponds to one user turn (0-indexed after the opener).

_STUB_INITIAL = (
    "Thanks for sharing — I've read through your idea. "
    "Before I break this into tasks I want to make sure I capture it right.\n\n"
    "**Who are the primary users of this product**, and what core problem does it solve for them?"
)

_STUB_FOLLOW_UPS = [
    (
        "Good context. Let's nail down scope — "
        "**what does the MVP look like to you?** "
        "What must ship on day one versus what can come later? "
        "Any stack preferences or existing systems to integrate with?"
    ),
    (
        "Almost there. Last thing: **what's the expected scale and timeline?** "
        "Quick internal prototype, a public MVP, or a full production system?"
    ),
]

_STUB_READY = (
    "I think I have a solid picture of what you're building. "
    "Ready to turn this into tickets whenever you are!"
    "\n__PM_READY__"
)


# ─── LLM caller (swap this when ready) ───────────────────────────────────────

def _call_llm(system_prompt: str, history: list[dict]) -> str:
    """
    Sends `history` to the LLM under `system_prompt` and returns the raw reply.

    history format:
        [{"role": "user" | "assistant", "content": "..."}]

    TODO: Replace the stub below with a real API call, e.g.:
        import anthropic
        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=1024,
            system=system_prompt,
            messages=history,
        )
        return response.content[0].text
    """
    # ── STUB — count user turns to pick a canned reply ──────────────────────
    user_turns = sum(1 for m in history if m["role"] == "user")

    if user_turns == 1:
        return _STUB_INITIAL

    stub_idx = user_turns - 2          # maps turn 2 → index 0, turn 3 → index 1, etc.
    if stub_idx < len(_STUB_FOLLOW_UPS):
        return _STUB_FOLLOW_UPS[stub_idx]

    return _STUB_READY


# ─── Public API used by routes ────────────────────────────────────────────────

def get_initial_message(idea_text: str) -> str:
    """
    Called once when a conversation is created.
    Sends the user's opening idea to the LLM and returns the PM's first reply.
    `idea_text` is stored as the first user turn in the history.
    """
    history = [{"role": "user", "content": idea_text}]
    raw = _call_llm(PM_SYSTEM_PROMPT, history)
    result = parse_agent_reply(raw)
    return result["displayText"]


def get_pm_response(
    history: list[dict],
    user_message_count: int,
) -> tuple[str, bool, dict | None]:
    """
    Called every time the user sends a follow-up message.

    history  — full conversation so far (role/content dicts, newest last).
    user_message_count — total user messages including the one just sent.

    Returns: (display_text, is_ready, tickets_or_None)
    """
    raw = _call_llm(PM_SYSTEM_PROMPT, history)
    result = parse_agent_reply(raw)
    return result["displayText"], result["isReady"], result["tickets"]
