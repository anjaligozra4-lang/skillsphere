from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.database import get_db
from app.models import Candidate, Recruiter, User


security = HTTPBearer(auto_error=False)


def _decode_user_from_credentials(
    credentials: HTTPAuthorizationCredentials | None,
    db: Session,
    required: bool = True,
) -> User | None:
    settings = get_settings()
    if credentials is None:
        if required:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return None
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        token_type = payload.get("type")
        if token_type is not None and token_type != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type",
            )
        user_id = int(payload["sub"])
    except HTTPException:
        raise
    except (JWTError, KeyError, TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Inactive or unknown user",
        )
    return user


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    user = _decode_user_from_credentials(credentials, db, required=True)
    assert user is not None
    return user


get_current_user = current_user


def optional_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> User | None:
    return _decode_user_from_credentials(credentials, db, required=False)


def require_roles(*roles: str):
    def guard(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return user
    return guard


def get_or_create_recruiter_profile(db: Session, user: User) -> Recruiter:
    """Ensure an authenticated recruiter user has an associated Recruiter profile row, preventing 500 crashes."""
    recruiter = db.scalar(select(Recruiter).where(Recruiter.user_id == user.id))
    if recruiter is None:
        recruiter = Recruiter(user_id=user.id)
        db.add(recruiter)
        db.commit()
        db.refresh(recruiter)
    return recruiter


def get_or_create_candidate_profile(db: Session, user: User) -> Candidate:
    """Ensure an authenticated candidate user has an associated Candidate profile row, preventing 500 crashes."""
    candidate = db.scalar(select(Candidate).where(Candidate.user_id == user.id))
    if candidate is None:
        candidate = Candidate(user_id=user.id)
        db.add(candidate)
        db.commit()
        db.refresh(candidate)
    return candidate
