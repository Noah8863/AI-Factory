import base64
import os
import requests
from dotenv import load_dotenv

# This command looks for the .env file in your backend folder 
# and loads the variables into os.environ
load_dotenv()

# Now we can grab the token using its label
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_USERNAME = os.getenv("GITHUB_USERNAME")

def get_repo():
    try:
        from git import Repo
        return Repo(os.getcwd())
    except ImportError:
        print("❌ GitPython is not installed. Run: pip install GitPython")
        return None
    except Exception as e:
        print(f"❌ Failed to get repo: {e}")
        return None

def prepare_branch(branch_name: str):
    try:
        repo = get_repo()
        if not repo:
            return False
        repo.git.checkout('-b', branch_name)
        return True
    except Exception as e:
        print(f"❌ Failed to prepare branch: {e}")
        return False

def commit_and_push(repo_name: str, branch_name: str, commit_message: str):
    repo = get_repo()
    if not repo:
        return False

    # 1. Stage all changes currently in the directory
    # 'A=True' is the equivalent of 'git add .'
    repo.git.add(A=True) 

    # 2. Commit the changes
    repo.index.commit(commit_message)

    # 3. Construct the "Authenticated" URL 
    # This uses your organization name instead of your personal username
    token = os.getenv("GITHUB_TOKEN")
    org_name = "AI-Factory-Labs" # <--- Change this to your actual Org name
    
    # Format: https://<token>@github.com/<org>/<repo>.git
    auth_url = f"https://{token}@github.com/{org_name}/{repo_name}.git"

    # 4. Push to the Organization
    try:
        # We ensure 'origin' points to the new organization repo
        if 'origin' in repo.remotes:
            repo.remote(name='origin').set_url(auth_url)
        else:
            repo.create_remote('origin', auth_url)
            
        # Push the local branch to the remote organization
        repo.git.push('origin', branch_name)
        print(f"🚀 Success! Changes pushed to {org_name}/{repo_name}")
        return True
    except Exception as e:
        print(f"❌ Push failed: {e}")
        return False
    
def create_org_repo(repo_name: str) -> dict | None:
    """
    Creates a private repo in the AI-Factory-Labs GitHub org.

    Returns a dict on success:
      { "url": str, "created": bool }   (created=False means it already existed)
    Returns None on failure.
    """
    token = os.getenv("GITHUB_TOKEN")
    org_name = "AI-Factory-Repos"

    url = f"https://api.github.com/orgs/{org_name}/repos"

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }

    data = {
        "name": repo_name,
        "private": True,   # keep user projects private by default
        "auto_init": True, # creates a README so the repo isn't empty
    }

    response = requests.post(url, json=data, headers=headers)

    if response.status_code == 201:
        repo_url = response.json().get("html_url", f"https://github.com/{org_name}/{repo_name}")
        print(f"✨ Created new repository: {repo_url}")
        return {"url": repo_url, "created": True}
    elif response.status_code == 422:
        # Repo already exists — surface the URL anyway
        repo_url = f"https://github.com/{org_name}/{repo_name}"
        print(f"ℹ️ Repository already exists: {repo_url}")
        return {"url": repo_url, "created": False}
    else:
        print(f"❌ Failed to create repo (status {response.status_code}): {response.text}")
        return None
    
def write_file_to_repo(
    repo_name: str,
    file_path: str,
    content: str,
    branch: str = "main",
    commit_message: str = "",
) -> bool:
    """
    Create or update a single file in a GitHub repo via the Contents API.
    The org is read from GITHUB_ORG (defaults to AI-Factory-Repos).

    Returns True on success, False on failure.
    """
    token    = os.getenv("GITHUB_TOKEN")
    org_name = os.getenv("GITHUB_ORG", "AI-Factory-Repos")
    url      = f"https://api.github.com/repos/{org_name}/{repo_name}/contents/{file_path}"

    headers = {
        "Authorization": f"token {token}",
        "Accept":        "application/vnd.github.v3+json",
    }

    # If the file already exists we need its SHA to perform an update.
    sha: str | None = None
    existing = requests.get(url, headers=headers, params={"ref": branch})
    if existing.status_code == 200:
        sha = existing.json().get("sha")

    body: dict = {
        "message": commit_message or f"AI Dev: add {file_path}",
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "branch":  branch,
    }
    if sha:
        body["sha"] = sha

    resp = requests.put(url, json=body, headers=headers)
    if resp.status_code in (200, 201):
        return True

    print(
        f"❌ Failed to write {file_path} to {repo_name}: "
        f"{resp.status_code} {resp.text[:200]}"
    )
    return False


def deploy_agent_work(repo_name: str, branch_name: str, commit_message: str):
    # 1. Ensure the repo exists in the Org
    if not create_org_repo(repo_name):
        return "Failed at repo creation step."

    # 2. Prepare the local branch
    if not prepare_branch(branch_name):
        return "Failed at branch preparation step."

    # 3. Commit and Push the work
    if commit_and_push(repo_name, branch_name, commit_message):
        return f"🚀 Work successfully deployed to {repo_name}/{branch_name}"
    
    return "Failed at push step."


def create_branch(repo_name: str, branch_name: str, base_branch: str = "main") -> bool:
    """
    Create a new branch in the remote repo from the tip of base_branch.

    Uses the Git Refs API so no local clone is needed.
    Returns True on success (or if the branch already exists), False on error.
    """
    token    = os.getenv("GITHUB_TOKEN")
    org_name = os.getenv("GITHUB_ORG", "AI-Factory-Repos")
    headers  = {
        "Authorization": f"token {token}",
        "Accept":        "application/vnd.github.v3+json",
    }

    # 1. Resolve the SHA of the base branch
    ref_url = (
        f"https://api.github.com/repos/{org_name}/{repo_name}"
        f"/git/refs/heads/{base_branch}"
    )
    ref_resp = requests.get(ref_url, headers=headers)
    if ref_resp.status_code != 200:
        print(f"❌ Could not resolve base branch '{base_branch}': {ref_resp.text[:200]}")
        return False

    base_sha = ref_resp.json()["object"]["sha"]

    # 2. Create the new branch ref
    create_url = f"https://api.github.com/repos/{org_name}/{repo_name}/git/refs"
    body = {
        "ref": f"refs/heads/{branch_name}",
        "sha": base_sha,
    }
    resp = requests.post(create_url, json=body, headers=headers)
    if resp.status_code == 201:
        return True
    if resp.status_code == 422:
        # Branch already exists — that's fine
        return True

    print(f"❌ Failed to create branch '{branch_name}': {resp.status_code} {resp.text[:200]}")
    return False


def create_pull_request(
    repo_name: str,
    branch_name: str,
    base_branch: str = "main",
    title: str = "",
    body: str = "",
) -> dict | None:
    """
    Open a pull request from *branch_name* → *base_branch*.

    Returns {"url": str, "number": int} on success, None on failure.
    """
    token    = os.getenv("GITHUB_TOKEN")
    org_name = os.getenv("GITHUB_ORG", "AI-Factory-Repos")
    url      = f"https://api.github.com/repos/{org_name}/{repo_name}/pulls"
    headers  = {
        "Authorization": f"token {token}",
        "Accept":        "application/vnd.github.v3+json",
    }
    payload = {
        "title": title or f"AI Agent: {branch_name}",
        "head":  branch_name,
        "base":  base_branch,
        "body":  body,
    }

    resp = requests.post(url, json=payload, headers=headers)
    if resp.status_code in (200, 201):
        data = resp.json()
        return {"url": data.get("html_url", ""), "number": data.get("number", 0)}

    print(
        f"❌ Failed to create PR for {branch_name} → {base_branch}: "
        f"{resp.status_code} {resp.text[:200]}"
    )
    return None


# ── CI / CD workflow ──────────────────────────────────────────────────────────

# A minimal GitHub Actions workflow that installs deps, runs lint / test
# (if scripts exist), and deploys for both Node.js (backend) and static
# frontend projects.
_CI_WORKFLOW_YAML = """\
# Auto-generated by AI Factory
name: CI / CD

on:
  push:
    branches: [main]

jobs:
  backend:
    name: Backend – Build & Test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run backend checks (if backend/ exists)
        run: |
          if [ ! -d backend ]; then
            echo "No backend/ directory found — skipping backend job."
            exit 0
          fi
          cd backend
          if [ -f requirements.txt ]; then
            python -m pip install --upgrade pip
            pip install -r requirements.txt
          fi
          if [ -f package.json ]; then
            npm install
            npm test --if-present
            npm run lint --if-present
          fi

  frontend:
    name: Frontend – Build
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 18
      - name: Build frontend (if frontend/ exists)
        run: |
          if [ ! -d frontend ]; then
            echo "No frontend/ directory found — skipping frontend build."
            exit 0
          fi
          cd frontend
          if [ -f package.json ]; then
            npm install
            npm run build --if-present
          fi

  deploy:
    name: Deploy to GitHub Pages
    needs: [backend, frontend]
    if: github.ref == 'refs/heads/main' && github.event_name == 'push'
    runs-on: ubuntu-latest
    permissions:
      pages: write
      id-token: write
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 18
      - name: Build frontend
        run: |
          if [ -d frontend ] && [ -f frontend/package.json ]; then
            cd frontend
            npm install
            npm run build --if-present
          fi
      - name: Prepare deploy folder
        run: |
          mkdir -p _site
          if [ -d frontend/dist ]; then
            cp -r frontend/dist/* _site/
          elif [ -d frontend/build ]; then
            cp -r frontend/build/* _site/
          elif [ -d frontend ]; then
            cp -r frontend/* _site/ 2>/dev/null || true
          else
            echo "No frontend output found to deploy."
          fi
      - uses: actions/upload-pages-artifact@v3
        with:
          path: _site
      - id: deployment
        uses: actions/deploy-pages@v4
"""


def deploy_ci_workflow(repo_name: str) -> bool:
    """
    Write a GitHub Actions CI/CD workflow into the repo on the main branch.

    Should only be called after ALL tickets are done (no pending / failed).
    Returns True on success, False on failure.
    """
    return write_file_to_repo(
        repo_name=repo_name,
        file_path=".github/workflows/ci.yml",
        content=_CI_WORKFLOW_YAML,
        branch="main",
        commit_message="AI Agent: add CI/CD workflow (GitHub Actions)",
    )