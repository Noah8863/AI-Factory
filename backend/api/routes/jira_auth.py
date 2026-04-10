"""
Jira / Atlassian OAuth 2.0 (3LO) flow
──────────────────────────────────────
GET /api/auth/jira/login
    • Requires the user's Bearer token as a query-param (?token=<jwt>) because
      this endpoint is visited via a browser redirect, not an Axios call, so
      Authorization headers are not available.
    • Builds the Atlassian consent-screen URL, encodes a short-lived signed
      "state" JWT (carries user_id + nonce for CSRF protection), and redirects.

GET /api/auth/jira/callback
    • Atlassian redirects here with ?code=<auth_code>&state=<state_jwt>
      (or ?error=<reason> on denial).
    • Decodes the state JWT to recover the user_id (no server-side session needed).
    • POSTs the auth code to Atlassian's token endpoint to exchange for tokens.
    • Upserts the access_token / refresh_token / expires_at into jira_tokens.
    • Redirects the browser back to the frontend.
"""

import os
import uuid
import logging
from datetime import datetime, timedelta
from urllib.parse import urlencode

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.database import get_db
from models.jira_token import JiraToken
from models.user import User
from services.auth_service import SECRET_KEY, ALGORITHM
from services.jira_service import get_user_jira_projects, JiraServiceError

load_dotenv()

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth/jira", tags=["jira-oauth"])
_bearer = HTTPBearer()

# ── Config from environment ───────────────────────────────────────────────────
JIRA_CLIENT_ID     = os.getenv("JIRA_CLIENT_ID", "")
JIRA_CLIENT_SECRET = os.getenv("JIRA_CLIENT_SECRET", "")
JIRA_REDIRECT_URI  = os.getenv("JIRA_REDIRECT_URI", "http://localhost:8000/api/auth/jira/callback")
FRONTEND_URL       = os.getenv("FRONTEND_URL", "http://localhost:5173")

# Atlassian endpoints
ATLASSIAN_AUTH_URL   = "https://auth.atlassian.com/authorize"
ATLASSIAN_TOKEN_URL  = "https://auth.atlassian.com/oauth/token"

# Scopes required by the Jira integration
JIRA_SCOPES = " ".join([
    "read:jira-user",
    "read:jira-work",
    "write:jira-work",
    "offline_access",   # grants a refresh_token
])

# Short TTL for the state JWT (10 minutes — only needs to survive the redirect round-trip)
STATE_TOKEN_EXPIRE_MINUTES = 10
STATE_AUDIENCE = "jira_oauth_state"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _create_state_token(user_id: int) -> str:
    """Return a signed JWT that encodes user_id + a random nonce.
    Used as the OAuth 'state' parameter for CSRF protection."""
    expire = datetime.utcnow() + timedelta(minutes=STATE_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub":   str(user_id),
        "nonce": str(uuid.uuid4()),   # prevents replay
        "aud":   STATE_AUDIENCE,
        "exp":   expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def _decode_state_token(state: str) -> int:
    """Decode and validate the state JWT. Returns user_id on success.
    Raises HTTPException(400) on any failure."""
    try:
        payload = jwt.decode(
            state,
            SECRET_KEY,
            algorithms=[ALGORITHM],
            audience=STATE_AUDIENCE,
        )
        return int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state parameter.")


def _decode_bearer_token(token: str, db: Session) -> User:
    """Validate the user's normal access token (passed as query param).
    Returns the User row, or raises 401."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid or expired access token.")

    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found or inactive.")
    return user


def _upsert_jira_token(
    db: Session,
    user_id: int,
    access_token: str,
    refresh_token: str | None,
    expires_at: datetime,
) -> JiraToken:
    """Insert or update the jira_tokens row for this user."""
    row = db.query(JiraToken).filter(JiraToken.user_id == user_id).first()
    now = datetime.utcnow()

    if row:
        row.access_token  = access_token
        row.refresh_token = refresh_token
        row.expires_at    = expires_at
        row.updated_at    = now
    else:
        row = JiraToken(
            user_id=user_id,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
        )
        db.add(row)

    db.commit()
    db.refresh(row)
    return row


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/login")
def jira_login(
    token: str = Query(..., description="The user's AI Factory access token (Bearer JWT)."),
    db:    Session = Depends(get_db),
):
    """
    Redirect the authenticated user to Atlassian's OAuth consent screen.

    The frontend should open this URL directly in the browser tab:
        GET /auth/jira/login?token=<access_token>
    """
    if not JIRA_CLIENT_ID:
        raise HTTPException(
            status_code=503,
            detail="Jira integration is not configured on this server (JIRA_CLIENT_ID missing).",
        )

    # Validate the user's access token and look them up
    user = _decode_bearer_token(token, db)

    # Build the signed state parameter
    state = _create_state_token(user.id)

    # Construct the Atlassian authorization URL
    params = urlencode({
        "audience":      "api.atlassian.com",
        "client_id":     JIRA_CLIENT_ID,
        "scope":         JIRA_SCOPES,
        "redirect_uri":  JIRA_REDIRECT_URI,
        "state":         state,
        "response_type": "code",
        "prompt":        "consent",   # ensures we always receive a refresh_token
    })
    auth_url = f"{ATLASSIAN_AUTH_URL}?{params}"

    logger.info("Redirecting user %s to Atlassian consent screen.", user.id)
    return RedirectResponse(auth_url)


@router.get("/callback")
async def jira_callback(
    code:  str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    error_description: str | None = Query(None),
    db:    Session = Depends(get_db),
):
    """
    Atlassian redirects here after the user approves (or denies) the consent screen.

    On success: exchanges the auth code for tokens, saves them, redirects to frontend.
    On denial:  redirects to frontend with an error query param.
    """
    # ── User denied access ────────────────────────────────────────
    if error:
        logger.warning("Jira OAuth denied: %s — %s", error, error_description)
        redirect = f"{FRONTEND_URL}/jira/callback?error={error}"
        return RedirectResponse(redirect)

    # ── Validate required params ──────────────────────────────────
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing 'code' or 'state' parameter.")

    # ── Decode state to recover user_id ───────────────────────────
    user_id = _decode_state_token(state)

    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    # ── Exchange authorization code for tokens ────────────────────
    token_payload = {
        "grant_type":    "authorization_code",
        "client_id":     JIRA_CLIENT_ID,
        "client_secret": JIRA_CLIENT_SECRET,
        "code":          code,
        "redirect_uri":  JIRA_REDIRECT_URI,
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.post(
                ATLASSIAN_TOKEN_URL,
                json=token_payload,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Atlassian token exchange failed: %s — %s",
                exc.response.status_code,
                exc.response.text,
            )
            raise HTTPException(
                status_code=502,
                detail=f"Atlassian token exchange failed: {exc.response.text}",
            )
        except httpx.RequestError as exc:
            logger.error("Network error during Atlassian token exchange: %s", exc)
            raise HTTPException(status_code=502, detail="Could not reach Atlassian servers.")

    token_data = resp.json()

    access_token  = token_data["access_token"]
    refresh_token = token_data.get("refresh_token")          # present when offline_access scope granted
    expires_in    = int(token_data.get("expires_in", 3600))  # seconds; Atlassian default is 3600
    expires_at    = datetime.utcnow() + timedelta(seconds=expires_in)

    # ── Persist tokens ────────────────────────────────────────────
    _upsert_jira_token(
        db=db,
        user_id=user_id,
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
    )

    logger.info("Jira tokens saved for user %s (expires %s).", user_id, expires_at.isoformat())

    # ── Redirect back to the frontend ─────────────────────────────
    return RedirectResponse(f"{FRONTEND_URL}/jira/callback?success=1")


@router.get("/status")
def jira_status(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
):
    """
    Returns whether the authenticated user has a connected Jira account.
    Called by the frontend JiraCallback page to confirm token persistence.
    """
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    connected = (
        db.query(JiraToken).filter(JiraToken.user_id == user_id).first() is not None
    )
    return {"connected": connected}


@router.get("/projects")
async def jira_list_projects(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
):
    """
    Return all Jira projects the authenticated user can access, plus the
    currently selected project key (if any).

    Response shape:
        {
            "cloud_id":             str,
            "projects":             [{"key": str, "name": str, "id": str}, ...],
            "selected_project_key": str | null
        }
    """
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    try:
        result = await get_user_jira_projects(user_id, db)
    except JiraServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    token_row = db.query(JiraToken).filter(JiraToken.user_id == user_id).first()
    result["selected_project_key"] = token_row.jira_project_key if token_row else None

    return result


class _ProjectSelect(BaseModel):
    project_key: str
    cloud_id:    str


@router.patch("/project")
def jira_select_project(
    body: _ProjectSelect,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
):
    """
    Persist the user's chosen Jira project key and cloud ID.
    The PM agent will send tickets to this project from now on.
    """
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    token_row = db.query(JiraToken).filter(JiraToken.user_id == user_id).first()
    if not token_row:
        raise HTTPException(
            status_code=404,
            detail="No Jira connection found for this account. Please connect Jira first.",
        )

    token_row.jira_project_key = body.project_key
    token_row.jira_cloud_id    = body.cloud_id
    token_row.updated_at       = datetime.utcnow()
    db.commit()

    logger.info(
        "User %s selected Jira project '%s' on cloud '%s'.",
        user_id, body.project_key, body.cloud_id,
    )
    return {"project_key": body.project_key, "cloud_id": body.cloud_id}
