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

from agents.pm_agent import PM_SYSTEM_PROMPT, parse_agent_reply

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

    if parsed.get("tickets") is None:
        logger.warning(
            "run_tasking: LLM response did not contain parseable ticket JSON. "
            "Raw output (first 500 chars): %s", raw[:500]
        )

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
) -> str:
    """
    Generate a README.md from the PM conversation history.

    Args:
        history:      PM conversation messages (role/content dicts).
        project_name: Human-friendly project title derived from the repo slug.
        live_url:     Optional GitHub Pages URL to embed in the Live Demo section.

    Returns the raw Markdown string ready to be committed to the repo.
    """
    live_url_line = (
        f"The project is deployed and live at: {live_url}\n"
        "Include this URL in the Live Demo section.\n\n"
        if live_url
        else ""
    )
    readme_prompt = (
        f"The project is called \"{project_name}\".\n\n"
        f"{live_url_line}"
        "Based on the conversation history above, write a README.md for this project.\n"
        "The project has already been built and deployed. Write the README as if it "
        "is being added to the repository root."
    )
    messages = history + [{"role": "user", "content": readme_prompt}]

    response = _client.messages.create(
        model=_MODEL,
        max_tokens=4096,
        system=_README_SYSTEM_PROMPT,
        messages=messages,
    )
    return response.content[0].text
