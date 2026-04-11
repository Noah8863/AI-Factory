import os
import anthropic
from agents.frontend_agent import FRONTEND_SYSTEM_PROMPT
from services.github_service import deploy_agent_work

_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

async def run_frontend_task(ticket_desc: str, tech_stack: str, repo_name: str):
    # Format the prompt with the specific tech stack
    system_msg = FRONTEND_SYSTEM_PROMPT.format(tech_stack=tech_stack)
    
    response = _client.messages.create(
        model="claude-3-5-sonnet-20240620",
        max_tokens=4000,
        system=system_msg,
        messages=[{"role": "user", "content": ticket_desc}]
    )
    
    code_content = response.content[0].text
    
    # In a real scenario, you'd write the code to disk here.
    # Then, trigger the push:
    # deploy_agent_work(repo_name, "feat/frontend-update", "AI Dev: Frontend Task")
    
    return code_content