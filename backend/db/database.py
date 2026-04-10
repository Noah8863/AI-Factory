import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# Load environment variables from the .env file
load_dotenv()

# Retrieve the DATABASE_URL from your .env
# It will now correctly use: postgresql://postgres:claude@localhost:5432/ai_factory
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("No DATABASE_URL found in environment variables. Check your .env file.")

# For PostgreSQL, we do not need the 'connect_args' used by SQLite.
# This fixes the crash you were experiencing.
engine = create_engine(DATABASE_URL)

# Configure the session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase):
    """Standard SQLAlchemy Declarative Base for models"""
    pass

def get_db():
    """Dependency for FastAPI routes to get a database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()