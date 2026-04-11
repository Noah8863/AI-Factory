"""
Temporary developer-testing routes.
These endpoints bypass the normal agent flow and are used to validate
individual capabilities (e.g. GitHub repo creation) in isolation.

TODO: Remove this file before shipping to production.
"""
import logging
import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.github_service import create_org_repo

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dev", tags=["dev"])


class CreateRepoRequest(BaseModel):
    repo_name: str = "test-repo"


class CreateRepoResponse(BaseModel):
    repo_url: str
    repo_name: str
    already_existed: bool


@router.post("/create-github-repo", response_model=CreateRepoResponse)
def dev_create_github_repo(payload: CreateRepoRequest):
    """
    [DEV] Directly trigger GitHub org-repo creation without going through the
    PM agent flow. Useful for testing the GitHub token and org permissions.
    """
    logger.info(f"[DEV] create-github-repo called with repo_name={payload.repo_name!r}")

    result = create_org_repo(payload.repo_name)
    if result is None:
        token_set = bool(os.getenv("GITHUB_TOKEN"))
        raise HTTPException(
            status_code=502,
            detail=f"GitHub API call failed. GITHUB_TOKEN present={token_set}. Check token permissions and org settings.",
        )

    return CreateRepoResponse(
        repo_url=result["url"],
        repo_name=payload.repo_name,
        already_existed=not result["created"],
    )
