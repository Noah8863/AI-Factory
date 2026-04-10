import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db.database import get_db
from models.user import User
from models.user_settings import UserSettings
from schemas.user import UserRegister, UserLogin, UserRead, TokenResponse
from services.auth_service import hash_password, verify_password, create_access_token, get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(payload: UserRegister, db: Session = Depends(get_db)):
    try:
        logger.info(f"Register attempt: email={payload.email}, username={payload.username}")
        
        # Check if email already exists
        existing_email = db.query(User).filter(User.email == payload.email).first()
        if existing_email:
            logger.warning(f"Email already registered: {payload.email}")
            raise HTTPException(status_code=400, detail="Email already registered")
        
        # Check if username already exists
        existing_username = db.query(User).filter(User.username == payload.username).first()
        if existing_username:
            logger.warning(f"Username already taken: {payload.username}")
            raise HTTPException(status_code=400, detail="Username already taken")

        # Create new user
        user = User(
            email=payload.email,
            username=payload.username,
            hashed_password=hash_password(payload.password),
            display_name=payload.display_name,
        )
        db.add(user)
        db.flush()
        logger.info(f"User created with ID: {user.id}")

        # Create default settings automatically for every new user
        db.add(UserSettings(user_id=user.id))
        db.commit()
        db.refresh(user)
        logger.info(f"User settings created for user {user.id}")

        token = create_access_token(user.id)
        logger.info(f"Access token created for user {user.id}")
        
        return TokenResponse(
            access_token=token,
            user=UserRead.model_validate(user),
        )
    except HTTPException as he:
        logger.error(f"HTTP Exception in register: {he.detail}")
        raise
    except ValueError as ve:
        logger.error(f"Validation error in register: {str(ve)}")
        raise HTTPException(status_code=400, detail=f"Validation error: {str(ve)}")
    except Exception as e:
        logger.error(f"Unexpected error in register: {type(e).__name__}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/login", response_model=TokenResponse)
def login(payload: UserLogin, db: Session = Depends(get_db)):
    try:
        logger.info(f"Login attempt: email={payload.email}")
        user = db.query(User).filter(User.email == payload.email).first()
        if not user or not verify_password(payload.password, user.hashed_password):
            logger.warning(f"Failed login attempt for email: {payload.email}")
            raise HTTPException(status_code=401, detail="Invalid email or password")

        token = create_access_token(user.id)
        logger.info(f"Login successful for user {user.id}")
        
        return TokenResponse(
            access_token=token,
            user=UserRead.model_validate(user),
        )
    except HTTPException as he:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in login: {type(e).__name__}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/me", response_model=UserRead)
def get_me(current_user: User = Depends(get_current_user)):
    return UserRead.model_validate(current_user)
