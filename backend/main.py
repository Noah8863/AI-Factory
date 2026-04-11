import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from db.database import Base, engine
from models import idea as _idea_model              # noqa: F401
from models import conversation as _conv_model      # noqa: F401
from models import message as _msg_model            # noqa: F401
from models import user as _user_model              # noqa: F401
from models import user_settings as _user_settings_model  # noqa: F401
from models import jira_token as _jira_token_model        # noqa: F401
from api.routes.ideas import router as ideas_router
from api.routes.conversations import router as conversations_router
from api.routes.auth import router as auth_router
from api.routes.users import router as users_router
from api.routes.jira_auth import router as jira_auth_router
from api.routes.dev import router as dev_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create all database tables on startup
Base.metadata.create_all(bind=engine)
logger.info("Database tables created/verified")

# Add new columns to existing tables (idempotent — safe to run on every boot)
with engine.connect() as _conn:
    _conn.execute(text(
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS github_repo_name VARCHAR(255)"
    ))
    _conn.execute(text(
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS github_repo_url VARCHAR(512)"
    ))
    _conn.commit()
logger.info("Column migrations applied")

app = FastAPI(title="AI Factory API", version="0.1.0")

# IMPORTANT: CORS must be the FIRST middleware added so it runs LAST (after routers)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174", 
        "http://localhost:5175",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
        "http://127.0.0.1:5175",
        "https://ai-factory-production-1f41.up.railway.app",
        "https://ai-factory-production-bb66.up.railway.app"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api")
app.include_router(jira_auth_router, prefix="/api")
app.include_router(users_router, prefix="/api")
app.include_router(ideas_router, prefix="/api")
app.include_router(conversations_router, prefix="/api")
app.include_router(dev_router, prefix="/api")


@app.get("/")
def root():
    return {"message": "AI Factory API is running"}


@app.get("/hello")
def hello():
    return {"message": "Hello, World!"}


@app.get("/test-cors")
def test_cors():
    """Test endpoint to verify CORS is working"""
    logger.info("test-cors endpoint called")
    return {"status": "ok", "message": "CORS is working!"}



