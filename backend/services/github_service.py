import os
import requests
from git import Repo
from dotenv import load_dotenv

# This command looks for the .env file in your backend folder 
# and loads the variables into os.environ
load_dotenv()

# Now we can grab the token using its label
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_USERNAME = os.getenv("GITHUB_USERNAME")

def get_repo():
    try:
        return Repo(os.getcwd())
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
    
def create_org_repo(repo_name: str):
    token = os.getenv("GITHUB_TOKEN")
    org_name = "AI-Factory-Labs" # Your Org Name
    
    url = f"https://api.github.com/orgs/{org_name}/repos"
    
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    data = {
        "name": repo_name,
        "private": True, # Keep user projects private by default
        "auto_init": True # This creates a README so the repo isn't empty
    }
    
    response = requests.post(url, json=data, headers=headers)
    
    if response.status_code == 201:
        print(f"✨ Created new repository: {org_name}/{repo_name}")
        return True
    elif response.status_code == 422:
        print(f"ℹ️ Repository {repo_name} already exists.")
        return True
    else:
        print(f"❌ Failed to create repo: {response.json()}")
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