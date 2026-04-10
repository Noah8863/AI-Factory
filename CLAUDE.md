# Project Profile: AI Factory

## Project Overview
"AI Factory" is an autonomous multi-agent system designed to turn high-level ideas into codebases. 
- **User Flow**: User logs in -> Chats with a **PM Agent** to define requirements.
- **Workflow**: PM Agent generates granular JIRA tickets (split by Frontend/Backend).
- **Execution**: Specialized **Developer Agents** (FE/BE) pick up tickets, write code, and push to a linked GitHub repository.

## Tech Stack
- **Frontend**: React.js (Vite), Tailwind CSS, SASS (SCSS), Material Icons
- **Backend**: Python 3.10+, FastAPI, Uvicorn (ASGI Server)
- **Database**: SQLAlchemy (ORM) with SQLite (Development)
- **Agent Framework**: [Add your library here, e.g., LangChain/LangGraph or CrewAI]
- **Integrations**: JIRA API (Ticketing), GitHub API (Code Push)

## System Architecture & Agent Roles
1. **PM Agent**: Gathers requirements, defines scope, and creates "bite-sized" JIRA tickets.
2. **Backend Dev Agent**: Specialized in Python/FastAPI; consumes BE-tagged tickets.
3. **Frontend Dev Agent**: Specialized in React/Tailwind; consumes FE-tagged tickets.

## Build & Development Commands

### Frontend (Root or /frontend)
- Install Dependencies: `npm install`
- Start Dev Server: `npm run dev`
- Build for Production: `npm run build`
- Lint Code: `npm run lint`

### Backend (Root or /backend)
- Create Virtual Env: `python -m venv venv`
- Activate Env: `source venv/bin/activate` (Unix) or `venv\Scripts\activate` (Win)
- Install Dependencies: `pip install -r requirements.txt`
- Start API Server: `uvicorn main:app --reload`

## Project Structure & Conventions
- **Naming**: PascalCase for React components; snake_case for Python/Backend.
- **Task Management**: All tasks must be separated into "Frontend" and "Backend" labels in JIRA.
- **Styling**: Tailwind for layout; SASS (`.scss`) for complex themes; Material Icons for UI.
- **API**: RESTful conventions; Pydantic for data validation; Axios for FE requests.
- **Imports**: Absolute imports for Python; Alias imports (`@/components`) for React.

## Key Configurations
- **FastAPI**: Main framework for speed and automatic Swagger docs.
- **CORS**: Pre-configured to allow React dev server communication.
- **Pydantic**: Used for strict data validation between agents and the UI.