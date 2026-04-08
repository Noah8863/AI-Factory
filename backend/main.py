from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from db.database import Base, engine
from models import idea as _idea_model  # noqa: F401 — registers model with Base
from api.routes.ideas import router as ideas_router

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

app.include_router(ideas_router)


@app.get("/")
def root():
    return {"message": "AI Factory API is running"}


@app.get("/hello")
def hello():
    return {"message": "Hello, World!"}
