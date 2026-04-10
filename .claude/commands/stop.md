Stop the AI Factory project by terminating all running backend and frontend server processes.

Steps:
1. Kill any process using port 8000 (FastAPI/uvicorn backend):
   Run: `cmd /c "for /f "tokens=5" %a in ('netstat -aon ^| findstr :8000') do taskkill /F /PID %a" 2>/dev/null || true`
2. Kill any process using port 5173 (Vite/React frontend):
   Run: `cmd /c "for /f "tokens=5" %a in ('netstat -aon ^| findstr :5173') do taskkill /F /PID %a" 2>/dev/null || true`
3. Also kill any lingering uvicorn or node processes related to this project:
   Run: `pkill -f "uvicorn main:app" 2>/dev/null || true`
4. Confirm the ports are now free by running `netstat -ano | grep -E "8000|5173"` and reporting the result.
5. Report that all servers have been stopped.
