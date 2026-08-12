"""User authentication helpers."""

from sqlalchemy.orm import Session

from app.models import User
from app.services.security import hash_password, verify_password

MIN_PASSWORD_LENGTH = 8


def normalize_email(email: str) -> str:
    return email.strip().lower()


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.query(User).filter(User.email == normalize_email(email)).first()


def get_user_by_id(db: Session, user_id: int) -> User | None:
    return db.query(User).filter(User.id == user_id).first()


def user_count(db: Session) -> int:
    return db.query(User).count()


def registration_allowed(db: Session, *, allow_registration: bool) -> bool:
    return user_count(db) == 0 or allow_registration


def validate_password(password: str) -> str | None:
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    return None


def create_user(db: Session, email: str, password: str) -> User:
    normalized = normalize_email(email)
    if not normalized:
        raise ValueError("Email is required.")
    password_error = validate_password(password)
    if password_error:
        raise ValueError(password_error)
    if get_user_by_email(db, normalized):
        raise ValueError("An account with that email already exists.")

    user = User(email=normalized, password_hash=hash_password(password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    user = get_user_by_email(db, email)
    if not user:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user
