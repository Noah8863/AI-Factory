Start the AI Factory project by launching both the backend (FastAPI) and frontend (Vite/React) servers.

Steps:
1. Start the backend: activate the venv at `backend/venv/Scripts/activate`, then run `uvicorn main:app --reload` from the `backend/` directory in the background. Write output to `/tmp/backend.log`.
2. Start the frontend: run `npm run dev` from the `frontend/` directory in the background. Write output to `/tmp/frontend.log`.
3. Wait ~4 seconds, then read both log files to confirm both servers started successfully.
4. Report the running URLs:
   - Frontend: http://localhost:5173
   - Backend API: http://127.0.0.1:8000
   - Swagger Docs: http://127.0.0.1:8000/docs
