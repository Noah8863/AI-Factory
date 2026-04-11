"""
services/jira_service.py
────────────────────────
Handles all Jira Cloud API interactions on behalf of a user:

  1. get_valid_access_token(user_id, db)
       Loads the stored JiraToken row.  If the token is expired (or within a
       60-second buffer), it calls Atlassian's refresh endpoint, persists the
       rotated tokens, and returns the fresh access_token.
       Returns None if the user has no Jira token at all.

  2. push_tickets_to_jira(user_id, db, tickets)
       Convenience wrapper: gets a valid token, resolves the user's first
       Jira Cloud instance and first project, then creates one Jira issue per
       ticket dict produced by the PM agent.  Returns a list of created-issue
       dicts (id, key, url) — or raises JiraServiceError on hard failures.

Internal helpers (prefixed _) are not part of the public API.
"""

import os
import logging
from datetime import datetime, timedelta

import httpx
from dotenv import load_dotenv
from sqlalchemy.orm import Session

from models.jira_token import JiraToken

load_dotenv()

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
JIRA_CLIENT_ID     = os.getenv("JIRA_CLIENT_ID", "")
JIRA_CLIENT_SECRET = os.getenv("JIRA_CLIENT_SECRET", "")
ATLASSIAN_TOKEN_URL = "https://auth.atlassian.com/oauth/token"
ACCESSIBLE_RESOURCES_URL = "https://api.atlassian.com/oauth/token/accessible-resources"

# Refresh the token this many seconds before it actually expires to avoid
# race conditions between the check and the API call.
EXPIRY_BUFFER_SECONDS = 60

# Jira priority names that map directly from the PM agent's priority field.
_PRIORITY_MAP = {"High": "High", "Medium": "Medium", "Low": "Low"}


# ── Public exception ──────────────────────────────────────────────────────────
class JiraServiceError(Exception):
    """Raised when the Jira service encounters an unrecoverable error."""


# ── Token management ──────────────────────────────────────────────────────────

async def get_valid_access_token(user_id: int, db: Session) -> str | None:
    """
    Return a non-expired access_token for user_id, or None if the user has
    not connected Jira.

    Side-effect: if the stored token is expired, this function refreshes it
    and writes the new tokens back to the database before returning.
    """
    row: JiraToken | None = (
        db.query(JiraToken).filter(JiraToken.user_id == user_id).first()
    )
    if row is None:
        logger.debug("No Jira token found for user %s.", user_id)
        return None

    # Check expiry with a buffer so we don't use a token that expires mid-request.
    expiry_threshold = datetime.utcnow() + timedelta(seconds=EXPIRY_BUFFER_SECONDS)
    if row.expires_at <= expiry_threshold:
        logger.info("Jira token for user %s is expired/near-expiry — refreshing.", user_id)
        return await _refresh_token(row, db)

    return row.access_token


async def _refresh_token(row: JiraToken, db: Session) -> str:
    """
    Exchange the stored refresh_token for a new access_token using Atlassian's
    token endpoint.  The refresh token rotates on every call, so we persist
    the new one immediately.

    Raises JiraServiceError if the refresh fails (e.g. token was revoked).
    """
    if not row.refresh_token:
        raise JiraServiceError(
            "Cannot refresh Jira token for user %s: no refresh_token stored. "
            "The user must reconnect Jira." % row.user_id
        )

    payload = {
        "grant_type":    "refresh_token",
        "client_id":     JIRA_CLIENT_ID,
        "client_secret": JIRA_CLIENT_SECRET,
        "refresh_token": row.refresh_token,
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.post(
                ATLASSIAN_TOKEN_URL,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise JiraServiceError(
                "Atlassian refresh failed (%s): %s" % (exc.response.status_code, exc.response.text)
            ) from exc
        except httpx.RequestError as exc:
            raise JiraServiceError("Network error during token refresh: %s" % exc) from exc

    data = resp.json()
    new_access_token  = data["access_token"]
    new_refresh_token = data.get("refresh_token", row.refresh_token)  # rotate if provided
    expires_in        = int(data.get("expires_in", 3600))
    new_expires_at    = datetime.utcnow() + timedelta(seconds=expires_in)

    # Persist the rotated tokens
    row.access_token  = new_access_token
    row.refresh_token = new_refresh_token
    row.expires_at    = new_expires_at
    row.updated_at    = datetime.utcnow()
    db.commit()
    db.refresh(row)

    logger.info(
        "Jira token refreshed for user %s (new expiry: %s).",
        row.user_id,
        new_expires_at.isoformat(),
    )
    return new_access_token


# ── Cloud / project discovery ─────────────────────────────────────────────────

async def _get_accessible_resources(access_token: str) -> list[dict]:
    """
    Return the list of Jira Cloud sites the token has access to.
    Each entry contains at minimum: {"id": "<cloudId>", "name": "<siteName>", "url": "..."}.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(
                ACCESSIBLE_RESOURCES_URL,
                headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise JiraServiceError(
                "Failed to fetch accessible resources (%s): %s"
                % (exc.response.status_code, exc.response.text)
            ) from exc

    resources = resp.json()
    if not resources:
        raise JiraServiceError("No accessible Jira Cloud sites found for this token.")
    return resources


async def _get_first_project_key(access_token: str, cloud_id: str) -> str:
    """
    Return the key of the first available project on the given cloud instance.
    This is used as a fallback when the user has not yet selected a project.
    """
    url = f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/project/search"
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(
                url,
                params={"maxResults": 1, "orderBy": "name"},
                headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise JiraServiceError(
                "Failed to fetch Jira projects (%s): %s"
                % (exc.response.status_code, exc.response.text)
            ) from exc

    data   = resp.json()
    values = data.get("values", [])
    if not values:
        raise JiraServiceError("No Jira projects found in this cloud instance.")
    return values[0]["key"]


async def _get_all_projects(access_token: str, cloud_id: str) -> list[dict]:
    """
    Return the full, paginated list of Jira projects on the given cloud instance,
    ordered by name.  Each entry contains at minimum "key", "name", and "id".
    """
    url      = f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/project/search"
    projects: list[dict] = []
    start_at = 0
    per_page = 50

    async with httpx.AsyncClient(timeout=15.0) as client:
        while True:
            try:
                resp = await client.get(
                    url,
                    params={
                        "maxResults": per_page,
                        "startAt":    start_at,
                        "orderBy":    "name",
                    },
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept":        "application/json",
                    },
                )
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise JiraServiceError(
                    "Failed to list Jira projects (%s): %s"
                    % (exc.response.status_code, exc.response.text)
                ) from exc

            data  = resp.json()
            batch = data.get("values", [])
            projects.extend(batch)

            if data.get("isLast", True) or len(batch) < per_page:
                break
            start_at += per_page

    return projects


# ── Public project helper ─────────────────────────────────────────────────────

async def get_user_jira_projects(user_id: int, db: Session) -> dict:
    """
    Fetch all Jira projects the user has access to.

    Returns:
        {
            "cloud_id":  str,
            "projects":  [{"key": str, "name": str, "id": str}, ...]
        }

    Raises JiraServiceError if the user has no connected Jira account.
    """
    access_token = await get_valid_access_token(user_id, db)
    if access_token is None:
        raise JiraServiceError("User has no connected Jira account.")

    resources = await _get_accessible_resources(access_token)
    cloud_id  = resources[0]["id"]
    raw       = await _get_all_projects(access_token, cloud_id)

    return {
        "cloud_id": cloud_id,
        "projects": [
            {"key": p["key"], "name": p["name"], "id": p["id"]}
            for p in raw
        ],
    }


# ── Ticket creation ───────────────────────────────────────────────────────────

def _build_adf_description(text: str) -> dict:
    """
    Wrap plain text in Atlassian Document Format (ADF), which is required
    by the Jira REST API v3 description field.
    """
    return {
        "type":    "doc",
        "version": 1,
        "content": [
            {
                "type":    "paragraph",
                "content": [{"type": "text", "text": text}],
            }
        ],
    }


async def _create_single_ticket(
    access_token: str,
    cloud_id:    str,
    project_key: str,
    ticket:      dict,
    issue_type:  str = "Task",
) -> dict:
    """
    Create a single Jira issue.  Returns {"id": ..., "key": ..., "url": ...}.

    ticket fields expected (from PM agent JSON):
        title, description, priority, labels, type (backend | frontend)
    """
    url = f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/issue"

    # Merge the PM-agent label list with the ticket type so it's easy to
    # filter in Jira (e.g. label:backend or label:frontend).
    labels = list(ticket.get("labels", []))
    ticket_type = ticket.get("type", "")
    if ticket_type and ticket_type not in labels:
        labels.insert(0, ticket_type)

    # Jira priority names must match an existing priority in the project.
    priority_name = _PRIORITY_MAP.get(ticket.get("priority", "Medium"), "Medium")

    issue_body = {
        "fields": {
            "project":     {"key": project_key},
            "summary":     ticket.get("title", "(No title)"),
            "description": _build_adf_description(ticket.get("description", "")),
            "issuetype":   {"name": issue_type},
            "priority":    {"name": priority_name},
            "labels":      labels,
        }
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.post(
                url,
                json=issue_body,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept":        "application/json",
                    "Content-Type":  "application/json",
                },
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # Log the full response for debugging; don't crash the whole batch.
            logger.error(
                "Failed to create Jira ticket '%s' (%s): %s",
                ticket.get("title"),
                exc.response.status_code,
                exc.response.text,
            )
            return {
                "error":  exc.response.text,
                "title":  ticket.get("title"),
                "status": exc.response.status_code,
            }

    created = resp.json()
    site_url = f"https://api.atlassian.com/ex/jira/{cloud_id}"  # approximate; real URL in accessible-resources
    return {
        "id":    created["id"],
        "key":   created["key"],
        "title": ticket.get("title"),
        "url":   f"{site_url}/browse/{created['key']}",
    }


# ── Issue type resolution ─────────────────────────────────────────────────────

# Preferred issue type names in priority order.  The first one that exists in
# the target project is used; if none match we fall back to whatever the
# project offers first.
_PREFERRED_ISSUE_TYPES = ["Task", "Story", "Bug", "Subtask", "Sub-task"]


async def _get_project_issue_type(access_token: str, cloud_id: str, project_key: str) -> str:
    """
    Fetch the issue types available for *project_key* and return the best match.
    Prefers Task > Story > Bug, then falls back to the first available type.
    """
    url = f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/project/{project_key}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(
                url,
                headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "Could not fetch project issue types (%s): %s — defaulting to 'Task'.",
                exc.response.status_code, exc.response.text,
            )
            return "Task"

    issue_types = [it["name"] for it in resp.json().get("issueTypes", [])]
    logger.info("Available issue types for project %s: %s", project_key, issue_types)

    for preferred in _PREFERRED_ISSUE_TYPES:
        if preferred in issue_types:
            logger.info("Using issue type '%s' for project %s.", preferred, project_key)
            return preferred

    # Fall back to whatever the project has
    if issue_types:
        logger.info("Using fallback issue type '%s' for project %s.", issue_types[0], project_key)
        return issue_types[0]

    return "Task"  # last resort


# ── Main public entry point ───────────────────────────────────────────────────

async def push_tickets_to_jira(
    user_id: int,
    db:      Session,
    tickets: list[dict],
) -> list[dict]:
    """
    High-level entry point called by the PM agent service.

    1. Loads and (if necessary) refreshes the user's Jira token.
    2. Resolves the user's first accessible Jira Cloud instance.
    3. Resolves the first available project on that instance.
    4. Creates one Jira issue per ticket dict.
    5. Returns a list of result dicts (id, key, url — or error info on failure).

    If the user has no Jira token this returns [] silently (not an error).
    """
    # ── Step 1: token ─────────────────────────────────────────────
    access_token = await get_valid_access_token(user_id, db)
    if access_token is None:
        logger.info("User %s has no Jira token — skipping ticket creation.", user_id)
        return []

    # ── Step 2: cloud instance + project ─────────────────────────
    # Prefer the user's explicitly chosen project; fall back to first available.
    token_row = db.query(JiraToken).filter(JiraToken.user_id == user_id).first()

    if token_row and token_row.jira_cloud_id and token_row.jira_project_key:
        cloud_id    = token_row.jira_cloud_id
        project_key = token_row.jira_project_key
        logger.info(
            "Using stored Jira config (cloud: %s, project: %s) for user %s.",
            cloud_id, project_key, user_id,
        )
    else:
        resources   = await _get_accessible_resources(access_token)
        cloud_id    = resources[0]["id"]
        cloud_name  = resources[0].get("name", cloud_id)
        logger.info("Using Jira cloud '%s' (%s) for user %s.", cloud_name, cloud_id, user_id)
        project_key = await _get_first_project_key(access_token, cloud_id)
        logger.info("Using Jira project '%s' for ticket creation.", project_key)

    # ── Step 3: resolve issue type for this project ──────────────
    issue_type = await _get_project_issue_type(access_token, cloud_id, project_key)

    # ── Step 4: create tickets (sequentially to respect rate limits) ──
    results = []
    for ticket in tickets:
        result = await _create_single_ticket(access_token, cloud_id, project_key, ticket, issue_type)
        results.append(result)
        logger.info(
            "Jira ticket %s: %s — %s",
            "created" if "key" in result else "FAILED",
            result.get("key", result.get("error", "?")),
            ticket.get("title", "?"),
        )

    return results
