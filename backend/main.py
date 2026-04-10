from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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

# Create all database tables on startup
Base.metadata.create_all(bind=engine)

app = FastAPI(title="AI Factory API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(users_router)
app.include_router(ideas_router)
app.include_router(conversations_router)


@app.get("/")
def root():
    return {"message": "AI Factory API is running"}


@app.get("/hello")
def hello():
    return {"message": "Hello, World!"}
