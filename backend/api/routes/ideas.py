from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from db.database import get_db
from models.idea import Idea
from schemas.idea import IdeaCreate, IdeaRead

router = APIRouter(prefix="/ideas", tags=["ideas"])


@router.post("", response_model=IdeaRead, status_code=201)
def create_idea(payload: IdeaCreate, db: Session = Depends(get_db)):
    idea = Idea(content=payload.content)
    db.add(idea)
    db.commit()
    db.refresh(idea)
    return idea


@router.get("", response_model=list[IdeaRead])
def list_ideas(db: Session = Depends(get_db)):
    return db.query(Idea).order_by(Idea.created_at.desc()).all()


@router.get("/{idea_id}", response_model=IdeaRead)
def get_idea(idea_id: int, db: Session = Depends(get_db)):
    idea = db.query(Idea).filter(Idea.id == idea_id).first()
    if not idea:
        raise HTTPException(status_code=404, detail="Idea not found")
    return idea
