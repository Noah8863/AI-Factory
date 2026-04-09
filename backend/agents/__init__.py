"""
agents/
------
Each module in this package defines one AI agent:
  - system prompt
  - output parser

The service layer (services/) is responsible for all I/O:
calling the LLM, storing messages, and returning results to routes.
Nothing in this package should import from FastAPI, SQLAlchemy, or
make network requests — it is pure Python logic only.
"""

from agents.pm_agent import PM_SYSTEM_PROMPT, parse_agent_reply

__all__ = [
    "PM_SYSTEM_PROMPT",
    "parse_agent_reply",
]
