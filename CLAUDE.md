# AI Factory — Complete Project Reference

> **Purpose of this file:** Authoritative documentation for AI coding assistants, engineers, and agents working in this codebase. Every section is written to give an LLM the full context needed to make correct decisions without guessing.

---

## Table of Contents

1. [Project Overview & Vision](#1-project-overview--vision)
2. [Tech Stack](#2-tech-stack)
3. [Repository Structure](#3-repository-structure)
4. [Database Schema & ORM](#4-database-schema--orm)
5. [Backend API Routes](#5-backend-api-routes)
6. [Agent System — PM Agent](#6-agent-system--pm-agent)
7. [Agent System — Developer Agents](#7-agent-system--developer-agents)
8. [Agent Orchestration — agent_runner.py](#8-agent-orchestration--agent_runnerpy)
9. [Chat Log Lifecycle](#9-chat-log-lifecycle)
10. [JIRA Integration](#10-jira-integration)
11. [GitHub Integration](#11-github-integration)
12. [Authentication & Sessions](#12-authentication--sessions)
13. [Frontend Architecture](#13-frontend-architecture)
14. [End-to-End Flow Walkthrough](#14-end-to-end-flow-walkthrough)
15. [Environment Variables](#15-environment-variables)
16. [Build & Development Commands](#16-build--development-commands)
17. [Deployment](#17-deployment)
18. [Coding Conventions](#18-coding-conventions)
19. [State Machines](#19-state-machines)
20. [Known Limitations & Future Work](#20-known-limitations--future-work)

---

## 1. Project Overview & Vision

**AI Factory** is an end-to-end autonomous multi-agent system that transforms a plain-English idea into a fully scaffolded, GitHub-hosted codebase — no human developer required.

### User Journey (high level)
1. User signs up and connects their Jira account via OAuth.
2. User submits a natural-language idea (e.g., "Build me a recipe-sharing app").
3. A **PM Agent** (LLM-powered) asks clarifying questions one at a time until it has enough context.
4. User clicks **"Start Building"** — the PM Agent emits a structured JSON payload of Jira tickets.
5. Tickets are pushed to Jira Cloud. A private GitHub repository is created.
6. **Developer Agents** (Backend + Frontend) execute tickets in dependency order, writing complete files directly to the GitHub repo via the Contents API.
7. When all tickets are done, a CI/CD workflow and auto-generated README are committed.
8. Idea status transitions to `completed`. The user sees live links to the repo and Jira board.

### What makes this non-trivial
- The PM Agent maintains a full conversation history that guides ticket generation — no context is lost between messages.
- Developer Agents write **complete, production-intent files** (no `// TODO` placeholders) parsed from raw LLM JSON output.
- Dependency resolution runs tickets concurrently at the same sequence level (`asyncio.gather`) and serially across levels — correctness over speed.
- The entire pipeline is cancellable mid-run; the frontend polls for status at ~1 s intervals.

---

## 2. Tech Stack

| Layer | Technology | Version / Notes |
|---|---|---|
| Frontend Framework | React | 18.3, Vite dev server |
| Routing | React Router | v6 |
| HTTP Client | Axios | Custom instance with auth interceptor |
| Styling | Tailwind CSS + SASS | Tailwind for layout; `.scss` for complex themes |
| Icons | Material Icons | via Google Fonts CDN |
| Backend Framework | FastAPI + Uvicorn | 0.115.0, async ASGI |
| Language | Python | 3.10+ |
| ORM | SQLAlchemy | v2.0.36 |
| Database (dev) | SQLite | auto-created on startup |
| Database (prod) | PostgreSQL | hosted on Railway |
| LLM (PM Agent) | Claude Sonnet 4 | `claude-sonnet-4-20250514` |
| LLM (Dev Agents) | Claude Sonnet 4.6 | `claude-sonnet-4-6`, 16 384 token output |
| LLM SDK | Anthropic Python SDK | `anthropic` package |
| Jira | Atlassian OAuth 2.0 | REST API v3, ADF descriptions |
| GitHub | GitHub REST API | PAT token, Contents API |
| Deployment | Railway.app | V2 runtime, auto-scaling |

---

## 3. Repository Structure

```
AI-Factory/
├── backend/
│   ├── agents/                    # Raw LLM system prompts + output parsers
│   │   ├── pm_agent.py            # PM system prompt, __PM_READY__ token, JSON parser
│   │   ├── backend_agent.py       # Backend dev system prompt + JSON parser
│   │   └── frontend_agent.py      # Frontend dev system prompt + JSON parser
│   ├── api/
│   │   └── routes/
│   │       ├── auth.py            # /register, /login, /me
│   │       ├── jira_auth.py       # Jira OAuth 2.0 flow + project selection
│   │       ├── conversations.py   # PM chat, start-tasking, reopen, decline
│   │       ├── ideas.py           # CRUD ideas, per-idea ticket status
│   │       ├── users.py           # User settings, ideas/conversations list
│   │       ├── agents.py          # Run/cancel/retry dev agents, poll tickets
│   │       └── dev.py             # Dev-only testing endpoints
│   ├── db/
│   │   └── database.py            # Engine, SessionLocal, Base, get_db dependency
│   ├── models/                    # SQLAlchemy ORM models
│   │   ├── user.py
│   │   ├── idea.py
│   │   ├── conversation.py
│   │   ├── message.py
│   │   ├── ticket.py
│   │   ├── jira_token.py
│   │   └── user_settings.py
│   ├── schemas/                   # Pydantic request/response schemas
│   │   ├── user.py
│   │   ├── idea.py
│   │   ├── conversation.py
│   │   ├── message.py
│   │   ├── ticket.py
│   │   ├── jira_token.py
│   │   └── user_settings.py
│   ├── services/                  # Business logic (no HTTP concerns here)
│   │   ├── auth_service.py        # JWT creation/validation, bcrypt helpers
│   │   ├── pm_agent.py            # I/O: calls LLM, returns parsed PM output
│   │   ├── backend_agent.py       # I/O: calls LLM, returns backend file list
│   │   ├── frontend_agent.py      # I/O: calls LLM, returns frontend file list
│   │   ├── agent_runner.py        # Orchestrator: dependency graph, async execution
│   │   ├── jira_service.py        # Jira API: OAuth refresh, ticket CRUD, transitions
│   │   └── github_service.py      # GitHub API: repo create, file write, CI deploy
│   ├── main.py                    # App factory, CORS, route registration, DB init
│   ├── requirements.txt
│   └── railway.json               # Railway deployment config
│
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── Landing.jsx        # Hero, feature cards, CTA
│   │   │   ├── Login.jsx          # Email + password auth form
│   │   │   ├── Register.jsx       # 3-step wizard: profile → preferences → Jira
│   │   │   ├── Dashboard.jsx      # Core app: idea input, PM chat, history, dev progress
│   │   │   ├── Profile.jsx        # Avatar, display name, Jira project selector
│   │   │   └── JiraCallback.jsx   # OAuth redirect landing; polls for token confirmation
│   │   ├── components/
│   │   │   ├── ChatThread.jsx     # Full chat UI: messages, banners, dev progress panel
│   │   │   ├── DevProgress.jsx    # Ticket list with status icons, retry, collapse
│   │   │   ├── JiraSettings.jsx   # Jira project dropdown with save feedback
│   │   │   ├── Navbar.jsx         # Top navigation
│   │   │   └── ConnectionStatus.jsx # API health indicator
│   │   ├── context/
│   │   │   └── ThemeContext.jsx   # Dark/light mode provider; applies class to <html>
│   │   ├── utils/
│   │   │   └── api.js             # Axios instance + all API call helper functions
│   │   └── styles/
│   │       └── global.scss        # Global CSS/SASS reset and theme variables
│   ├── index.html
│   ├── vite.config.js             # Vite config + /api proxy to backend
│   ├── tailwind.config.js
│   ├── postcss.config.js
│   └── package.json
│
├── CLAUDE.md                      # This file
├── TODO                           # In-progress feature notes
└── .gitignore
```

---

## 4. Database Schema & ORM

### Engine & Sessions (`backend/db/database.py`)
- `DATABASE_URL` from environment; defaults to `sqlite:///./aifactory.db`.
- `SessionLocal` is a `sessionmaker` with `autocommit=False`, `autoflush=False`.
- `get_db()` is a FastAPI dependency that yields a session and always closes it.
- `Base.metadata.create_all(bind=engine)` is called in `main.py` on startup — **no Alembic migrations**. Additive column changes are applied manually in `main.py` with `ALTER TABLE` guards.

### Models

#### `User`
```
id            Integer PK
email         String  UNIQUE, indexed
username      String  UNIQUE, min 3 chars
hashed_password String
display_name  String  nullable
is_active     Boolean default=True
created_at    DateTime
updated_at    DateTime
```
Relationships: `ideas` (1→many), `conversations` (1→many), `jira_token` (1→1), `settings` (1→1).

#### `Idea`
```
id            Integer PK
user_id       Integer FK → users.id
title         String  nullable (derived from first message)
content       Text    (original user-submitted text)
status        String  "pending" | "processing" | "completed"
created_at    DateTime
updated_at    DateTime
```
Relationships: `conversations` (1→many), `user` (many→1).

#### `Conversation`
```
id                Integer PK
idea_id           Integer FK → ideas.id
user_id           Integer FK → users.id
status            String "active" | "ready_to_task" | "tasking" | "done"
cancelled         Boolean default=False  ← checked by agents at runtime
github_repo_name  String  nullable
github_repo_url   String  nullable
jira_project_key  String  nullable
jira_project_url  String  nullable
created_at        DateTime
updated_at        DateTime
```
Relationships: `messages` (1→many), `tickets` (1→many).

#### `Message`
```
id                Integer PK
conversation_id   Integer FK → conversations.id
role              String "user" | "agent"
content           Text
created_at        DateTime
```
> **Important for LLM:** When building the history array to send to the LLM, map `role="agent"` → `"assistant"` and `role="user"` → `"user"`. Full history is sent on every request.

#### `Ticket`
```
id              Integer PK
conversation_id Integer FK → conversations.id
ticket_id       String  e.g. "BE-1", "FE-3"  (PM-assigned, not Jira key)
jira_issue_key  String  nullable  e.g. "PROJ-12"  (from Jira API)
type            String  "backend" | "frontend"
phase           String  "Foundation" | "Core" | "Integration" | "Polish"
sequence        Integer (1-based; tickets at same level run concurrently)
depends_on      JSON    list of ticket_id strings this ticket must wait for
priority        String  "High" | "Medium" | "Low"
title           String
description     Text    (acceptance criteria written by PM Agent)
story_points    Integer nullable
labels          JSON    list of strings
status          String  "pending" | "in_progress" | "done" | "failed" | "cancelled"
error_msg       Text    nullable  (last 5 traceback frames on failure)
agent_output    Text    nullable  (raw JSON from agent execution)
created_at      DateTime
updated_at      DateTime
```

#### `JiraToken`
```
id               Integer PK
user_id          Integer FK → users.id, UNIQUE
access_token     String
refresh_token    String nullable
expires_at       DateTime
jira_cloud_id    String nullable  (Atlassian site cloud ID)
jira_project_key String nullable  (user-selected project, e.g. "PROJ")
created_at       DateTime
updated_at       DateTime
```

#### `UserSettings`
```
id                    Integer PK
user_id               Integer FK → users.id, UNIQUE
theme                 String "light" | "dark"
notifications_enabled Boolean
updated_at            DateTime
```

---

## 5. Backend API Routes

All routes are prefixed `/api`. JWT-protected routes require `Authorization: Bearer <token>`.

### Auth (`/api/auth`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/auth/register` | No | Create account. Returns JWT + `UserRead`. |
| POST | `/auth/login` | No | Email + password → JWT + `UserRead`. |
| GET | `/auth/me` | JWT | Returns current `UserRead`. |

### Jira OAuth (`/api/auth/jira`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/auth/jira/login` | `?token=<jwt>` | Redirects browser to Atlassian consent screen. Creates short-lived state JWT. |
| GET | `/auth/jira/callback` | No | Atlassian redirects here with `code` + `state`. Exchanges for tokens, saves to DB, redirects to frontend `/jira/callback`. |
| GET | `/auth/jira/status` | JWT | Returns `{ connected: bool, jira_project_key: str | null }`. |
| GET | `/auth/jira/projects` | JWT | Returns `{ cloud_id, projects: [{key, name, id}] }`. |
| PATCH | `/auth/jira/project` | JWT | Body: `{ jira_project_key }`. Saves chosen project. |

### Ideas (`/api/ideas`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/ideas` | JWT | Create idea. Body: `{ content }`. |
| GET | `/ideas` | JWT | List all user ideas. |
| GET | `/ideas/{id}` | JWT | Single idea. |
| DELETE | `/ideas/{id}` | JWT | Cascade-deletes conversations, messages, tickets. |
| GET | `/ideas/{id}/conversation` | JWT | Latest conversation for this idea. |
| GET | `/ideas/{id}/tickets` | JWT | Ticket list with statuses for the idea's latest conversation. |

### Conversations (`/api/conversations`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/conversations` | JWT | Body: `{ idea_id }`. Creates conversation, calls PM Agent for first message. Saves agent reply as `Message`. |
| GET | `/conversations/{id}` | No | Returns full conversation with all `Message` objects. |
| POST | `/conversations/{id}/messages` | JWT | Body: `{ content }`. Saves user message, calls PM Agent with full history, saves agent reply. Returns updated conversation. |
| POST | `/conversations/{id}/start-tasking` | JWT | Triggers ticket generation (see §14). Returns `TaskingResult`. |
| POST | `/conversations/{id}/reopen` | No | Sets status back to `"active"`. |
| POST | `/conversations/{id}/decline-tasking` | No | Marks conversation `"done"` without executing tickets. |

**`TaskingResult` schema:**
```json
{
  "conversation": { ...ConversationRead },
  "messages": [ ...MessageRead ],
  "tickets": [ ...TicketRead ],
  "jira_tickets_created": [ { "id", "key", "title", "url" } ],
  "jira_error": "string or null"
}
```

### Agents (`/api/agents`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/{conversation_id}/run` | JWT | Queues `run_all_tickets_bg` as FastAPI `BackgroundTask`. |
| GET | `/{conversation_id}/tickets` | No | Returns `[TicketRead]` with current statuses — used for polling. |
| POST | `/{conversation_id}/cancel` | JWT | Sets `conversation.cancelled = True`. Agents check this flag. |
| POST | `/{conversation_id}/tickets/{ticket_db_id}/retry` | JWT | Resets ticket to `"pending"`, re-queues background task for that one ticket. |

### Users (`/api/users`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/users/me/settings` | JWT | Returns `UserSettings`. |
| PATCH | `/users/me/settings` | JWT | Body: `{ theme?, notifications_enabled? }`. |
| GET | `/users/me/ideas` | JWT | Same as `/ideas`. |
| GET | `/users/me/conversations` | JWT | All conversations for user. |

### Dev Testing (`/api/dev`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/dev/create-github-repo` | No | Manually test GitHub repo creation. Body: `{ repo_name }`. |

---

## 6. Agent System — PM Agent

### Location
- **System prompt:** `backend/agents/pm_agent.py` → `PM_SYSTEM_PROMPT`
- **I/O service:** `backend/services/pm_agent.py`

### Responsibilities & Phases

#### Phase 1 — Discovery (Conversation)
The PM Agent is a conversational requirements analyst. It asks **one clarifying question at a time** in a warm, professional tone. It probes for:
- The target users and problem statement
- Must-have MVP features (aim for 2–3)
- Tech stack preferences (defaults: Node.js + Express + MongoDB for backend, Vanilla JS for frontend if user has no preference)
- Definition of success / acceptance criteria
- Explicit non-goals (what's out of scope)

When the PM Agent has enough information, it appends the token `__PM_READY__` to its message. The backend service (`services/pm_agent.py`) detects this token, strips it, and sets `is_ready = True` in the return value.

#### Phase 2 — Ticket Generation
Triggered when the user clicks "Start Building" (`start-tasking` route). The service sends the full conversation history with a special instruction appended: `"ACTION: Start tasking. Generate the Jira tickets now."`. The PM Agent returns a JSON blob (not markdown) with this structure:

```json
{
  "projectName": "Recipe Sharing App",
  "projectSummary": "A web app where users...",
  "githubRepoName": "recipe-sharing-app",
  "jiraProjectKey": "RSA",
  "tickets": [
    {
      "id": "BE-1",
      "type": "backend",
      "title": "Set up Express server with MongoDB connection",
      "description": "Acceptance criteria:\n- ...",
      "priority": "High",
      "phase": "Foundation",
      "sequence": 1,
      "dependsOn": [],
      "storyPoints": 3,
      "labels": ["backend", "foundation", "setup"]
    },
    {
      "id": "FE-1",
      "type": "frontend",
      "title": "Create recipe card component",
      "description": "...",
      "priority": "Medium",
      "phase": "Core",
      "sequence": 2,
      "dependsOn": ["BE-1"],
      ...
    }
  ]
}
```

**Ticket ID conventions:**
- `BE-N` for backend tickets
- `FE-N` for frontend tickets
- Sequence numbers are 1-based and **must respect `dependsOn`** — a ticket can only be at sequence N if all its dependencies are at sequence < N.
- Phase progression: Foundation → Core → Integration → Polish

#### Phase 3 — Continuation (Adding Requirements)
If the user continues chatting after tickets are generated (conversation re-opened), the PM Agent enters a second discovery pass. It only asks about **new** features, not re-questioning already-ticketed ones. When `start-tasking` is called again:
- The service finds the last `"ACTION: Start tasking..."` sentinel in the history.
- Only messages **after** that checkpoint are sent to the LLM.
- New tickets have sequence numbers continuing from where the last round left off.

### LLM Config
```python
# Normal chat turn
model = "claude-sonnet-4-20250514"
max_tokens = 512

# Ticket generation (start-tasking)
model = "claude-sonnet-4-20250514"
max_tokens = 4096
```

---

## 7. Agent System — Developer Agents

### Location
- **Backend agent system prompt:** `backend/agents/backend_agent.py` → `BACKEND_SYSTEM_PROMPT`
- **Frontend agent system prompt:** `backend/agents/frontend_agent.py` → `FRONTEND_SYSTEM_PROMPT`
- **I/O services:** `backend/services/backend_agent.py`, `backend/services/frontend_agent.py`

### Backend Developer Agent

**Default tech stack:** Node.js 18+, Express.js, MongoDB with Mongoose ODM.
Override via env var `BACKEND_TECH_STACK`.

**System prompt rules (critical for correctness):**
- Output is **strictly JSON**, no prose, no markdown fences around the outer object.
- All `content` fields must be **complete file contents** — no ellipsis, no `// TODO`, no `...rest of file`.
- File paths must start with `backend/`.
- `action` is `"create"` or `"update"`.
- The agent receives the full ticket description (title + acceptance criteria) plus the existing file tree of the GitHub repo (so it knows what already exists).

**Output schema:**
```json
{
  "summary": "One-sentence description of what was done",
  "files": [
    {
      "path": "backend/src/routes/recipes.js",
      "content": "const express = require('express');\n...",
      "action": "create"
    }
  ],
  "notes": "Optional: migration steps, env vars needed, etc."
}
```

### Frontend Developer Agent

**Default tech stack:** Vanilla JavaScript (ES6+), HTML5, CSS3, Fetch API.
Override via env var `FRONTEND_TECH_STACK`.

Same output rules as backend agent; file paths must start with `frontend/`.

### LLM Config (both agents)
```python
model = "claude-sonnet-4-6"
max_tokens = 16384   # large output — agents write full files
```

### Output Parsing
Both agents use a `parse_developer_output(raw_text)` function that:
1. Strips any accidental markdown fences (` ```json ... ``` `).
2. Attempts `json.loads()`.
3. Falls back to regex extraction of the first `{...}` block if initial parse fails.
4. Returns `None` on complete failure (ticket marked `failed`).

---

## 8. Agent Orchestration — `agent_runner.py`

**Location:** `backend/services/agent_runner.py`

This is the core execution engine. All functions are `async`.

### Key Functions

#### `store_tickets(conversation_id, tickets_data, jira_results, db)`
- Iterates the PM-generated ticket JSON array.
- Creates a `Ticket` row for each entry.
- Maps `ticket.ticket_id` → `jira_issue_key` from the `jira_results` array.
- Returns `[Ticket]`.

#### `get_runnable_tickets(conversation_id, ticket_type, db)`
- Fetches all tickets for the conversation of the given type (`"backend"` or `"frontend"`).
- Returns only tickets where `status == "pending"` AND all `depends_on` tickets are `"done"`.
- Orders by `sequence ASC`.

#### `run_ticket(ticket_db_id, user_id, conversation, db)`
- Sets ticket `status = "in_progress"`, transitions Jira issue to "In Progress".
- Builds the ticket prompt: `f"Ticket: {ticket.title}\n\nDescription:\n{ticket.description}"`.
- Fetches current file tree from GitHub repo to give agent context.
- Calls `run_backend_task()` or `run_frontend_task()` depending on ticket type.
- Writes each file in the agent output to the GitHub repo via `write_file_to_repo()`.
- Sets ticket `status = "done"` (or `"failed"` if any step throws).
- Transitions Jira issue to "Done".
- Returns `True` on success, `False` on failure.

#### `run_all_tickets(conversation_id, user_id, db)`
Runs the full dependency-aware execution loop:
```
while True:
    runnable = get_runnable_tickets(...)
    if not runnable: break
    if conversation.cancelled: mark remaining as "cancelled"; break
    group = tickets at the lowest sequence number in runnable
    results = await asyncio.gather(*[run_ticket(t) for t in group])
    # repeat until no more runnable tickets
return { done, failed, still_pending }
```
Tickets at the **same sequence number** run **concurrently** via `asyncio.gather`. Tickets at different sequence levels run **serially** (each level waits for the previous).

#### `run_all_tickets_bg(conversation_id, user_id)`
- Thin wrapper for `BackgroundTasks`.
- Creates its own `SessionLocal()` (does **not** reuse the request-scoped session).
- Calls `run_all_tickets`, then:
  - If all tickets done: calls `deploy_ci_workflow(repo_name)` + `generate_readme(...)` + commits both to GitHub.
  - Sets `idea.status = "completed"` or `"failed"`.
  - Closes its own DB session in `finally`.

---

## 9. Chat Log Lifecycle

### Storage
Every turn is persisted immediately:
- **User message:** saved before calling the LLM.
- **Agent reply:** saved after LLM returns.
- Table: `messages`. Columns: `id`, `conversation_id`, `role` (`"user"` | `"agent"`), `content`, `created_at`.

### History Reconstruction
On every `/conversations/{id}/messages` call:
1. Fetch all `Message` rows for the conversation ordered by `created_at ASC`.
2. Map to LLM format:
   ```python
   [{"role": "assistant" if m.role == "agent" else "user", "content": m.content}]
   ```
3. Pass the full list as the `messages` parameter to the Anthropic SDK.
4. The system prompt is passed separately as `system=PM_SYSTEM_PROMPT`.

This means **the LLM always has full context** — there is no summarization or truncation. For very long conversations this may approach token limits; the current PM prompt is optimized to keep replies short (512 max tokens).

### Tasking Checkpoint Mechanism
When `start-tasking` is called after a prior round of tickets (Phase 3):
1. The service scans the stored messages list in reverse.
2. It finds the last message with content `"ACTION: Start tasking. Generate the Jira tickets now."`.
3. Only messages **after** this sentinel are passed to the LLM for the new ticket generation call.
4. This prevents the LLM from re-generating tickets for already-completed features.

### Ticket ↔ Message Relationship
Tickets are stored in the `tickets` table, **not** in `messages`. The connection is:
- `Ticket.conversation_id` links to the `Conversation`.
- `Ticket.agent_output` stores the raw JSON string returned by the developer agent (for debugging).
- The PM agent's ticket JSON is **not** stored as a message — it is parsed and stored in `tickets` rows.

---

## 10. JIRA Integration

### OAuth 2.0 Flow (3LO)
1. Frontend calls `window.open('/api/auth/jira/login?token=<jwt>')`.
2. Backend validates JWT, creates a short-lived **state JWT** (5-min expiry) encoding `user_id`.
3. Browser is redirected to Atlassian consent screen with `state` param.
4. On approval, Atlassian redirects to `/api/auth/jira/callback?code=<code>&state=<state>`.
5. Backend decodes `state` → `user_id`, exchanges `code` for `access_token` + `refresh_token`.
6. Tokens saved to `jira_tokens` table (`expires_at` = now + 3600s).
7. Browser redirected to `{FRONTEND_URL}/jira/callback?success=1`.
8. Frontend polls `/auth/jira/status` every 2.5 s until `connected: true`.

### Token Refresh
`get_valid_access_token(user_id, db)` in `jira_service.py`:
- If `expires_at - now < 60s`: exchanges `refresh_token` for new tokens via Atlassian OAuth endpoint.
- Persists the rotated tokens to DB.
- Returns the (potentially refreshed) `access_token`.
- Returns `None` if no token exists.

### Ticket Creation in Jira
Called from `start-tasking` route via `push_tickets_to_jira(user_id, db, tickets, project_key, cloud_id)`:

1. For each ticket in the PM JSON array:
   - Calls `_create_single_ticket(token, cloud_id, project_key, ticket)`.
   - POST `https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/issue`.
   - Description uses **Atlassian Document Format (ADF)** with a metadata header:
     ```
     Phase: Foundation | Sequence: 1 | Depends On: (none)
     ─────────────────────────────
     {acceptance criteria from PM agent}
     ```
   - Labels include: ticket type, phase, sequence, dependency IDs.
2. Returns array of `{ id, key, title, url }` for successes and `{ error, title, status }` for failures.
3. The `jira_error` field in `TaskingResult` is non-null if any tickets failed.

### Issue Status Transitions
`transition_jira_issue(user_id, db, cloud_id, issue_key, target_status)`:
- Called by `agent_runner.py` when a ticket starts (`"In Progress"`) and completes (`"Done"`).
- Fetches available transitions for the issue, finds one matching `target_status` (case-insensitive).
- **Best-effort:** logs a warning but does not fail the ticket if transition fails.

### Project Selection
- Users list projects via `GET /auth/jira/projects`.
- Save selection via `PATCH /auth/jira/project`.
- Stored on `JiraToken.jira_project_key`.
- Auto-project creation is **disabled** in production (code exists in `jira_service.py` but is commented out in `conversations.py`).

---

## 11. GitHub Integration

### Repository Creation (`github_service.py`)
`create_org_repo(repo_name)`:
- POST `https://api.github.com/orgs/{GITHUB_ORG}/repos`.
- Creates a **private** repo with `auto_init=True` (initial commit with README placeholder).
- If 422 (already exists), fetches existing URL and returns it.
- Returns `{ url: str, created: bool }` or `None` on failure.

### File Writing
`write_file_to_repo(repo_name, file_path, content, branch="main", commit_message)`:
1. GET existing file SHA: `GET /repos/{GITHUB_ORG}/{repo_name}/contents/{file_path}`.
2. Base64-encode `content`.
3. PUT to Contents API with `{ message, content, sha? (if updating) }`.
4. Commit message format: `"AI Agent: [TICKET-ID] {summary} — {file_path}"`.
5. Returns `True` on success, `False` on failure (logs error).

### CI/CD Deployment
`deploy_ci_workflow(repo_name)`:
- Writes a GitHub Actions YAML to `.github/workflows/`.
- Typically includes: build, test, and GitHub Pages deploy steps.
- Called automatically when all tickets are `done`.

### README Generation
After all tickets complete:
1. Fetch all conversation messages from DB.
2. Call PM agent with a special "generate README" system prompt.
3. Inject `project_name` and `live_url` (deterministic: `https://{GITHUB_ORG}.github.io/{repo_name}/`).
4. PM agent returns raw Markdown.
5. Write to `README.md` on main branch.

### Error Handling
- GitHub errors in `write_file_to_repo` are logged at WARNING level and counted as `file_errors` in the agent result.
- If a file write fails, the ticket is not automatically marked `failed` (partial writes are tolerated).
- A ticket is only marked `failed` if the LLM call itself fails or output parsing returns `None`.

---

## 12. Authentication & Sessions

### JWT (Local Users)
- Library: PyJWT (via `python-jose`).
- Algorithm: HS256.
- Expiry: 7 days.
- Payload: `{ "sub": str(user_id), "exp": ... }`.
- Secret: `SECRET_KEY` env var.

`create_access_token(user_id)` → JWT string.
`get_current_user(credentials, db)` → `User` (FastAPI `Depends`).

### Password Hashing
- Library: `passlib[bcrypt]`.
- `hash_password(password)` → bcrypt hash.
- `verify_password(plain, hashed)` → bool.

### Frontend Storage
- JWT stored in `localStorage` as `aif_token`.
- User object stored as `aif_user` (JSON string).
- Avatar stored as `aif_avatar` (base64 data URL).
- Jira return URL stored as `aif_jira_return_to` (for redirect-back after OAuth).

### Axios Interceptor
```javascript
api.interceptors.request.use(config => {
  const token = localStorage.getItem('aif_token');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});
```

---

## 13. Frontend Architecture

### Routing (`src/main.jsx` or `App.jsx`)
| Path | Component | Notes |
|------|-----------|-------|
| `/` | `Landing` | Public |
| `/login` | `Login` | Redirects to `/dashboard` on success |
| `/register` | `Register` | 3-step wizard |
| `/dashboard` | `Dashboard` | Protected; central app page |
| `/profile` | `Profile` | Protected |
| `/jira/callback` | `JiraCallback` | OAuth landing |

### Dashboard State Machine
The Dashboard page (`Dashboard.jsx`) manages three views via tab state:

**"New Idea" tab:**
- Textarea with localStorage draft auto-save (`aif_draft_idea`).
- On submit: checks Jira status → calls `startConversation(text)` → switches to Chat tab.

**"Chat" tab:**
- Renders `<ChatThread>` component.
- `ChatThread` owns all conversation state: messages, sending state, agent ticket polling.

**"History" tab:**
- Lists all user ideas with status pills and quick-access buttons.

### ChatThread Component (`components/ChatThread.jsx`)
Key state:
```javascript
messages          // array of { id, role, content, _optimistic? }
status            // conversation status string
isSending         // bool: LLM call in flight
showReadyBanner   // bool: show "Start Building" banner
isTaskingLoading  // bool: start-tasking call in flight
agentTickets      // array of TicketRead
devInProcess      // bool: agents currently running (poll active)
```

Polling loop (while `devInProcess`):
```javascript
const interval = setInterval(async () => {
  const tickets = await getAgentTickets(conversationId);
  setAgentTickets(tickets);
  const allDone = tickets.every(t => ['done','failed','cancelled'].includes(t.status));
  if (allDone) { clearInterval(interval); setDevInProcess(false); }
}, 1000);
```

### API Utility (`utils/api.js`)
All API interactions go through this module. Functions map 1:1 to backend routes:

```javascript
// Conversations
startConversation(ideaContent)         → POST /ideas + POST /conversations
getConversation(id)                    → GET /conversations/{id}
sendMessage(convId, content)           → POST /conversations/{convId}/messages
startTasking(convId)                   → POST /conversations/{convId}/start-tasking
reopenConversation(convId)             → POST /conversations/{convId}/reopen
declineTasking(convId)                 → POST /conversations/{convId}/decline-tasking

// Agents
runAgents(convId)                      → POST /agents/{convId}/run
getAgentTickets(convId)                → GET /agents/{convId}/tickets
retryTicket(convId, ticketDbId)        → POST /agents/{convId}/tickets/{ticketDbId}/retry
cancelAgents(convId)                   → POST /agents/{convId}/cancel

// Ideas
submitIdea(content)                    → POST /ideas
getIdeas()                             → GET /ideas
getIdeaConversation(ideaId)            → GET /ideas/{ideaId}/conversation
deleteIdea(ideaId)                     → DELETE /ideas/{ideaId}
```

### ThemeContext
Wraps the entire app. Reads initial theme from `localStorage` (`aif_theme`). Applies `class="dark"` to `<html>` element. Components consume via `useContext(ThemeContext)`.

---

## 14. End-to-End Flow Walkthrough

This is the canonical execution path for a new project build.

```
1. User submits idea text
   └─ POST /ideas  →  Idea created (status="pending")
   └─ POST /conversations  →  Conversation created (status="active")
         └─ PM Agent called (get_initial_message)
         └─ First Message saved (role="agent")
         └─ Frontend shows message in chat

2. User ↔ PM Agent conversation
   └─ POST /conversations/{id}/messages  (repeat N times)
         └─ User Message saved (role="user")
         └─ Full history sent to LLM
         └─ Agent reply saved (role="agent")
         └─ If "__PM_READY__" detected → is_ready=True returned to frontend
         └─ Frontend shows "Start Building" banner

3. User clicks "Start Building"
   └─ POST /conversations/{id}/start-tasking
         a. Conversation status → "tasking"
         b. PM Agent called with full history + ACTION sentinel
         c. PM returns ticket JSON
         d. GitHub repo created (github_service.create_org_repo)
              └─ conversation.github_repo_name, github_repo_url saved
         e. Jira tickets created (jira_service.push_tickets_to_jira)
              └─ Per ticket: POST to Jira REST API v3
              └─ Returns [{id, key, title, url}]
         f. Tickets saved to DB (agent_runner.store_tickets)
              └─ jira_issue_key mapped from jira_results
         g. POST /agents/{id}/run called → queues BackgroundTask
         h. TaskingResult returned to frontend immediately

4. Background: agent_runner.run_all_tickets_bg
   └─ Creates own DB session
   └─ Idea status → "processing"
   └─ LOOP:
         a. get_runnable_tickets → tickets with all deps "done"
         b. Group by sequence number
         c. asyncio.gather(run_ticket for each in group)
              └─ Each run_ticket:
                    i.   ticket.status → "in_progress"
                    ii.  Jira issue → "In Progress"
                    iii. Fetch GitHub file tree for context
                    iv.  Call backend_agent or frontend_agent LLM
                    v.   Parse JSON output
                    vi.  For each file: write_file_to_repo
                    vii. ticket.status → "done" or "failed"
                    viii.Jira issue → "Done"
         d. Repeat until no runnable tickets remain
   └─ deploy_ci_workflow(repo_name)
   └─ generate_readme(history, project_name, live_url)
   └─ Commit README.md to GitHub
   └─ idea.status → "completed" or "failed"

5. Frontend polling
   └─ GET /agents/{id}/tickets  every ~1s while devInProcess
   └─ UI updates ticket statuses in real time
   └─ When all done/failed/cancelled → polling stops, show final state
```

---

## 15. Environment Variables

### Backend (`backend/.env`)
```bash
# LLM
ANTHROPIC_API_KEY=sk-ant-...

# Database
DATABASE_URL=postgresql://user:pass@host:5432/dbname
# (SQLite fallback if unset: sqlite:///./aifactory.db)

# Auth
SECRET_KEY=your-jwt-secret-32-chars-min

# Jira OAuth
JIRA_CLIENT_ID=your-atlassian-app-client-id
JIRA_CLIENT_SECRET=your-atlassian-app-secret
JIRA_REDIRECT_URI=https://your-backend.railway.app/api/auth/jira/callback

# Frontend URL (for Jira OAuth redirect)
FRONTEND_URL=https://your-frontend.railway.app

# GitHub
GITHUB_TOKEN=ghp_your_personal_access_token
GITHUB_ORG=AI-Factory-Repos  # org where repos are created

# Optional agent stack overrides
BACKEND_TECH_STACK=Python + FastAPI + PostgreSQL
FRONTEND_TECH_STACK=React + Tailwind CSS
```

### Frontend (`frontend/.env`)
```bash
VITE_API_BASE_URL=https://your-backend.railway.app
# In local dev, leave unset — Vite proxies /api to localhost:8001
```

---

## 16. Build & Development Commands

### Backend
```bash
cd backend
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8001
# Swagger UI: http://localhost:8001/docs
```

### Frontend
```bash
cd frontend
npm install
npm run dev       # http://localhost:5173 (proxies /api → :8001)
npm run build     # Production build → /dist
npm run lint      # ESLint
```

### Vite Proxy (dev only)
`frontend/vite.config.js` proxies `/api` to `http://localhost:8001` so the frontend doesn't need `VITE_API_BASE_URL` in local dev.

---

## 17. Deployment

### Backend (Railway.app)
- Config: `backend/railway.json`
- Build: RAILPACK auto-detects Python.
- Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Database: PostgreSQL service on Railway, connected via `DATABASE_URL`.
- Scaling: 1 replica, auto-restart on crash.
- DB schema: auto-applied on startup via `Base.metadata.create_all()`.

### Frontend (Railway / Static)
- `npm run build` produces `frontend/dist/`.
- Deploy as static files; set root to `frontend/dist`.
- `VITE_API_BASE_URL` must point to the deployed backend URL.

---

## 18. Coding Conventions

### Python / Backend
- **snake_case** for all variables, functions, and file names.
- **PascalCase** for SQLAlchemy model classes and Pydantic schemas.
- FastAPI route handlers are thin — call service functions, return schemas.
- Business logic lives in `services/`, not in route handlers.
- Use `Depends(get_db)` and `Depends(get_current_user)` for injection.
- Pydantic schemas mirror the ORM models; `orm_mode = True` (v1) / `from_attributes = True` (v2).
- All agent calls are `async def`; use `await` for I/O-bound operations.

### React / Frontend
- **PascalCase** for component files and function names.
- **camelCase** for variables, hooks, and helper functions.
- Alias imports: `@/components/...`, `@/utils/...` (configured in `vite.config.js`).
- Tailwind for layout and spacing; SCSS for animations, complex gradients, or repeated custom styles.
- Material Icons via `<span className="material-icons">icon_name</span>`.
- All API calls go through `utils/api.js` — never call `fetch` or `axios` directly in components.

---

## 19. State Machines

### Conversation Status
```
active  ──(user ready)──→  ready_to_task  ──(start-tasking)──→  tasking  ──(all done)──→  done
  ↑                                ↑
  └──(reopen)──────────────────────┘
```

### Idea Status
```
pending  ──(start-tasking)──→  processing  ──(all tickets done)──→  completed
                                                                  └─(any ticket failed)──→  failed
```

### Ticket Status
```
pending  ──(agent picks up)──→  in_progress  ──(success)──→  done
                                             └─(error)────→  failed  ──(retry)──→  pending
                                             └─(cancel)───→  cancelled
```

---

## 20. Known Limitations & Future Work

### Disabled / Partially Implemented
- **AI Personality:** Register page includes personality selection (concise/balanced/detailed) but it is not passed to the PM Agent system prompt.
- **Email Notifications:** Toggle in settings is saved but no emails are sent.
- **Jira Project Auto-Creation:** Code exists in `jira_service.py` but is commented out in `conversations.py`. Users must pre-create the project.

### Architectural Gaps
- **No WebSockets:** All real-time updates use REST polling at ~1 s intervals. Adding WebSocket support would reduce latency and server load.
- **No Authentication for Several Routes:** `GET /conversations/{id}`, `POST /conversations/{id}/reopen`, `POST /conversations/{id}/decline-tasking`, `GET /agents/{id}/tickets` are unauthenticated — any client with a conversation ID can read or modify state.
- **No Token Expiry Handling on Frontend:** If the JWT expires during a session, API calls fail silently (no redirect to login).
- **No User-Level Rate Limiting:** A single user could queue unlimited agent jobs.
- **No Cost Tracking:** LLM usage per user/project is not metered or capped.
- **SQLite in Dev, PostgreSQL in Prod:** Schema drift risk. No Alembic migrations — additive changes are applied in `main.py` manually.
- **Agent Output is Ephemeral:** `Ticket.agent_output` stores the raw JSON per ticket, but there's no UI to inspect it. Debugging failed tickets requires direct DB access.

### Suggested Improvements for AI Agents Working in This Codebase
- When modifying agent prompts, always test with a complete conversation history — the PM Agent is stateful and depends on prior context.
- When adding new API routes, check whether they need auth (`Depends(get_current_user)`). The unauthenticated routes above are a known gap, not a pattern to follow.
- When modifying the `Ticket` or `Conversation` models, remember there are no migrations — add columns defensively in `main.py` with `CREATE TABLE IF NOT EXISTS` / `ALTER TABLE` guards.
- When changing the PM Agent's ticket JSON schema, update `agent_runner.store_tickets()` and the `Ticket` model in sync — they are tightly coupled.
- The `__PM_READY__` token is the PM-to-backend signal for readiness. If you change the PM system prompt, ensure this token is still emitted in the right circumstances.
