"""
infrastructure/railway_client.py
─────────────────────────────────
Railway GraphQL API client.

Connects generated project backends to an existing Railway "Production Hub"
project.  Every generated backend becomes a new *service* inside that single
hub project — no new Railway projects are created.

Architecture note — why one hub project?
  Railway charges per project.  Grouping all generated backends as services
  inside one project is cheaper and keeps the Railway dashboard tidy.

Public API
──────────
  create_production_service(repo_url, service_name) → str | None
      Creates a Railway service inside the Production Hub linked to the
      generated project's GitHub repo.  Provisions a public domain and polls
      until the URL is confirmed active.  Returns the HTTPS backend URL or
      raises RailwayError on a known failure.

Exceptions
──────────
  RailwayError         — base class; always has a human-readable .message
  RailwayConflictError — service name already exists in the hub
  RailwayAuthError     — invalid or missing RAILWAY_API_TOKEN
  RailwayRateLimitError — API quota hit; back off and retry later

Environment variables
─────────────────────
  RAILWAY_API_TOKEN          — Personal API token from railway.app/account/tokens
  PRODUCTION_HUB_PROJECT_ID  — ID of the existing Railway hub project.
                               Found in the Railway dashboard URL:
                               railway.app/project/<PRODUCTION_HUB_PROJECT_ID>
  RAILWAY_TEAM_ID            — (optional) Team ID; only needed if the hub
                               project belongs to a team account.
"""

import logging
import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_RAILWAY_GQL = "https://backboard.railway.app/graphql/v2"

# Polling config for domain availability
_POLL_INTERVAL_SECONDS = 3
_POLL_MAX_ATTEMPTS     = 10


# ── Custom exceptions ─────────────────────────────────────────────────────────

class RailwayError(Exception):
    """Base Railway API error with a human-readable message."""
    def __init__(self, message: str, raw: object = None):
        super().__init__(message)
        self.message = message
        self.raw     = raw  # original API response or error payload for debugging


class RailwayConflictError(RailwayError):
    """A service with this name already exists in the Production Hub project."""


class RailwayAuthError(RailwayError):
    """RAILWAY_API_TOKEN is missing, expired, or does not have the required scope."""


class RailwayRateLimitError(RailwayError):
    """Railway API rate limit hit.  Back off before retrying."""


# ── Env helpers ───────────────────────────────────────────────────────────────

def _token() -> str:
    # Strip trailing '?' in case the value was copied from a Railway dashboard URL
    return os.getenv("RAILWAY_API_TOKEN", "").rstrip("?").strip()


def _hub_project_id() -> str:
    return os.getenv("PRODUCTION_HUB_PROJECT_ID", "").rstrip("?").strip()


# ── Low-level GraphQL transport ───────────────────────────────────────────────

def _gql(query: str, variables: dict) -> dict:
    """
    Execute a Railway GraphQL query or mutation.

    Returns the `data` dict on success.
    Raises the appropriate RailwayError subclass on failure so callers never
    have to inspect raw HTTP responses.
    """
    token = _token()
    if not token:
        raise RailwayAuthError(
            "RAILWAY_API_TOKEN is not set or is empty. "
            "Create a token at https://railway.app/account/tokens and add it to .env."
        )

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
    }

    try:
        resp = requests.post(
            _RAILWAY_GQL,
            json={"query": query, "variables": variables},
            headers=headers,
            timeout=30,
        )
    except requests.RequestException as exc:
        raise RailwayError(f"Railway API network error: {exc}") from exc

    # ── HTTP-level errors ─────────────────────────────────────────────────
    if resp.status_code == 401:
        raise RailwayAuthError(
            "Railway API returned 401 Unauthorized — check RAILWAY_API_TOKEN.",
            raw=resp.text,
        )
    if resp.status_code == 429:
        raise RailwayRateLimitError(
            "Railway API rate limit hit (HTTP 429). Wait a moment before retrying.",
            raw=resp.text,
        )
    if resp.status_code != 200:
        raise RailwayError(
            f"Railway API HTTP {resp.status_code}: {resp.text[:400]}",
            raw=resp.text,
        )

    body = resp.json()

    # ── GraphQL-level errors ──────────────────────────────────────────────
    if "errors" in body:
        errors = body["errors"]
        first  = errors[0] if errors else {}
        msg    = first.get("message", str(errors))
        code   = (first.get("extensions") or {}).get("code", "")

        msg_lower = msg.lower()
        if "already exists" in msg_lower or code in ("CONFLICT", "DUPLICATE"):
            raise RailwayConflictError(
                f"A service named this already exists in the Production Hub: {msg}",
                raw=errors,
            )
        if "unauthorized" in msg_lower or "forbidden" in msg_lower or code in ("UNAUTHORIZED", "FORBIDDEN"):
            raise RailwayAuthError(
                f"Railway API authorization error: {msg}",
                raw=errors,
            )
        if "rate" in msg_lower or code in ("RATE_LIMIT", "RATE_LIMITED", "TOO_MANY_REQUESTS"):
            raise RailwayRateLimitError(
                f"Railway API rate limit: {msg}",
                raw=errors,
            )
        raise RailwayError(f"Railway GraphQL error: {msg}", raw=errors)

    data = body.get("data")
    if data is None:
        raise RailwayError("Railway API returned no data and no errors — unexpected response.", raw=body)

    return data


# ── Railway operations ────────────────────────────────────────────────────────

def _get_hub_environment_id() -> str:
    """
    Fetch the production environment ID from the Production Hub project.

    Prefers the environment named 'production'; falls back to the first one.
    Raises RailwayError if the hub project ID is not configured or the query fails.
    """
    hub_id = _hub_project_id()
    if not hub_id:
        raise RailwayError(
            "PRODUCTION_HUB_PROJECT_ID is not set. "
            "Add the Railway project ID of your Production Hub to .env."
        )

    query = """
    query GetHubEnvironments($id: String!) {
      project(id: $id) {
        id
        environments {
          edges {
            node {
              id
              name
            }
          }
        }
      }
    }
    """
    data = _gql(query, {"id": hub_id})

    project = data.get("project")
    if not project:
        raise RailwayError(
            f"Production Hub project '{hub_id}' not found — check PRODUCTION_HUB_PROJECT_ID.",
            raw=data,
        )

    edges = project.get("environments", {}).get("edges", [])
    if not edges:
        raise RailwayError(
            f"Production Hub project '{hub_id}' has no environments.",
            raw=project,
        )

    for edge in edges:
        node = edge.get("node", {})
        if node.get("name", "").lower() == "production":
            return node["id"]

    # Fallback: first available environment
    return edges[0]["node"]["id"]


def _create_service_in_hub(service_name: str, repo_path: str) -> str:
    """
    Create a new Railway service in the Production Hub project, linked to a
    GitHub repo.  Railway immediately triggers a build.

    repo_path must be the "org/repo" slug, e.g. "AI-Factory-Repos/my-app".
    Returns the new service ID.
    Raises RailwayConflictError if the service name is already taken.
    """
    mutation = """
    mutation ServiceCreate($input: ServiceCreateInput!) {
      serviceCreate(input: $input) {
        id
        name
      }
    }
    """
    hub_id = _hub_project_id()
    variables = {
        "input": {
            "projectId": hub_id,
            "name":      service_name,
            "source": {
                "repo": repo_path,
            },
        }
    }
    data    = _gql(mutation, variables)
    service = data.get("serviceCreate")
    if not service or not service.get("id"):
        raise RailwayError(
            f"serviceCreate returned no service object for '{service_name}'.",
            raw=data,
        )

    logger.info(
        "Railway service created: id=%s name=%s (build triggered).",
        service["id"], service.get("name"),
    )
    return service["id"]


def _provision_domain(service_id: str, environment_id: str) -> str | None:
    """
    Provision a Railway-provided public domain (Static Gateway) for a service.

    Returns the bare domain string (e.g. "my-app-production.up.railway.app")
    immediately — Railway reserves the DNS entry even while the build is running.
    Returns None on failure (caller should poll as fallback).
    """
    mutation = """
    mutation ServiceDomainCreate($input: ServiceDomainCreateInput!) {
      serviceDomainCreate(input: $input) {
        id
        domain
      }
    }
    """
    data = _gql(mutation, {
        "input": {
            "serviceId":     service_id,
            "environmentId": environment_id,
        }
    })
    result = data.get("serviceDomainCreate")
    return result.get("domain") if result else None


def _poll_for_domain(service_id: str, environment_id: str) -> str | None:
    """
    Poll the Railway domains query until a service domain appears.

    Used as a fallback if _provision_domain() doesn't return a domain in
    its mutation response.  Polls every _POLL_INTERVAL_SECONDS seconds for
    up to _POLL_MAX_ATTEMPTS attempts.

    Returns the domain string or None if polling times out.
    """
    query = """
    query GetServiceDomains($serviceId: String!, $environmentId: String!) {
      domains(input: { serviceId: $serviceId, environmentId: $environmentId }) {
        serviceDomains {
          domain
        }
      }
    }
    """
    variables = {"serviceId": service_id, "environmentId": environment_id}

    for attempt in range(1, _POLL_MAX_ATTEMPTS + 1):
        logger.info(
            "Polling Railway for domain (service=%s, attempt %d/%d) …",
            service_id, attempt, _POLL_MAX_ATTEMPTS,
        )
        try:
            data    = _gql(query, variables)
            domains = data.get("domains", {}).get("serviceDomains", [])
            if domains:
                domain = domains[0].get("domain")
                if domain:
                    logger.info("Railway domain found via polling: %s", domain)
                    return domain
        except RailwayError as exc:
            logger.warning("Polling error (attempt %d): %s", attempt, exc)

        if attempt < _POLL_MAX_ATTEMPTS:
            time.sleep(_POLL_INTERVAL_SECONDS)

    return None


# ── Public entrypoint ─────────────────────────────────────────────────────────

def _repo_path_from_url(repo_url: str) -> str:
    """
    Convert a GitHub URL to an 'org/repo' path.

    Accepts both:
      https://github.com/AI-Factory-Repos/my-app
      AI-Factory-Repos/my-app          (already a path — returned as-is)
    """
    url = repo_url.rstrip("/")
    if "github.com" in url:
        # strip scheme + host, leaving /AI-Factory-Repos/my-app
        path = url.split("github.com")[-1].lstrip("/")
        # remove any .git suffix
        return path.removesuffix(".git")
    # Already in org/repo format
    return url


def create_production_service(repo_url: str, service_name: str) -> str:
    """
    Deploy a generated project's backend to the Railway Production Hub.

    Steps:
      1. Resolve the hub project's production environment ID.
      2. Create a new service in the hub linked to the GitHub repo
         (Railway auto-triggers a build immediately).
      3. Provision a Railway Static Gateway domain for the service.
      4. Return the HTTPS URL.

    Args:
        repo_url:      GitHub URL or 'org/repo' slug of the generated backend.
                       E.g. "https://github.com/AI-Factory-Repos/my-recipe-app"
                       or "AI-Factory-Repos/my-recipe-app".
        service_name:  Human-readable name for the Railway service.
                       Must be unique within the Production Hub project.
                       Conventionally equals the repo slug.

    Returns:
        The public HTTPS backend URL, e.g.
        "https://my-recipe-app-production.up.railway.app".

    Raises:
        RailwayAuthError       — missing / invalid RAILWAY_API_TOKEN
        RailwayConflictError   — service_name already exists in the hub
        RailwayRateLimitError  — API quota hit
        RailwayError           — any other Railway API failure
    """
    repo_path = _repo_path_from_url(repo_url)

    logger.info(
        "Deploying backend to Railway Production Hub — service='%s' repo='%s'",
        service_name, repo_path,
    )

    # ── 1. Resolve production environment ────────────────────────────────
    environment_id = _get_hub_environment_id()
    logger.info("Production Hub environment resolved: %s", environment_id)

    # ── 2. Create service (triggers Railway build) ────────────────────────
    service_id = _create_service_in_hub(service_name, repo_path)

    # ── 3. Provision public domain ────────────────────────────────────────
    logger.info("Provisioning Railway domain for service %s …", service_id)
    domain = _provision_domain(service_id, environment_id)

    if not domain:
        # Mutation didn't return domain inline — poll as fallback
        logger.info(
            "Domain not returned by mutation — polling for availability "
            "(up to %ds) …",
            _POLL_MAX_ATTEMPTS * _POLL_INTERVAL_SECONDS,
        )
        domain = _poll_for_domain(service_id, environment_id)

    if not domain:
        raise RailwayError(
            f"Failed to obtain a public domain for service '{service_name}' "
            f"after {_POLL_MAX_ATTEMPTS} polling attempts. "
            "Check the Railway dashboard and manually add a domain if needed.",
            raw={"service_id": service_id, "environment_id": environment_id},
        )

    backend_url = f"https://{domain}"
    logger.info(
        "Railway backend URL for '%s': %s "
        "(backend build is running asynchronously).",
        service_name, backend_url,
    )
    return backend_url
