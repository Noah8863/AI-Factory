# Project Profile: React-Python Web App

## Tech Stack
- **Frontend**: React.js (Vite), Tailwind CSS, SASS (SCSS), Material Icons
- **Backend**: Python 3.10+, FastAPI, Uvicorn (ASGI Server)
- **Database**: SQLAlchemy (ORM) with SQLite (Development)
- **Package Management**: npm (Frontend), pip / venv (Backend)

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
- **Naming**: Use PascalCase for React components and snake_case for Python functions/variables.
- **Styling**: 
  - Use Tailwind for layout and utility spacing.
  - Use SASS (`.scss`) for complex, reusable component styling or global themes.
  - Prioritize Material Icons for all iconography.
- **API**: Follow RESTful conventions. Backend should serve JSON responses.
- **Imports**: Use absolute imports for Python and alias imports (e.g., `@/components`) for React where possible.

## Missing Tools Added
- **FastAPI**: Chosen as the Python framework for its speed and automatic Swagger documentation.
- **Pydantic**: For data validation and settings management in Python.
- **Axios**: For frontend API requests to the Python backend.
- **CORS Middleware**: Pre-configured in backend to allow communication with the React dev server.