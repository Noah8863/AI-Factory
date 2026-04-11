import os
import anthropic
from agents.backend_agent import BACKEND_SYSTEM_PROMPT
from services.github_service import deploy_agent_work

_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

async def run_backend_task(ticket_desc: str, tech_stack: str, repo_name: str):
    system_msg = BACKEND_SYSTEM_PROMPT.format(tech_stack=tech_stack)
    
    response = _client.messages.create(
        model="claude-3-5-sonnet-20240620",
        max_tokens=4000,
        system=system_msg,
        messages=[{"role": "user", "content": ticket_desc}]
    )
    
    code_content = response.content[0].text
    
    # After writing files to disk:
    # deploy_agent_work(repo_name, "feat/backend-update", "AI Dev: Backend Task")
    
    return code_content