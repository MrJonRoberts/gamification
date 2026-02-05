from typing import Any
from fastapi import Depends, HTTPException, Request
from .extensions import db
from .models import User
from .security import decode_access_token
from .config import settings


class AnonymousUser:
    """Represents a non-authenticated user."""
    is_authenticated = False
    role = "anonymous"
    first_name = "Guest"
    email = None


def get_db() -> Any:
    """Dependency to provide a database session."""
    try:
        yield db.session
    finally:
        db.remove_session()


def get_current_user(request: Request, session=Depends(get_db)) -> User | AnonymousUser:
    """Retrieves the current user from a JWT token in cookies."""
    token = request.cookies.get(settings.AUTH_COOKIE_NAME)
    if not token:
        # Fallback to session for migration/compatibility
        user_id = request.session.get("user_id")
        if user_id:
            user = session.get(User, user_id)
            if user:
                return user
        return AnonymousUser()

    payload = decode_access_token(token)
    if not payload:
        return AnonymousUser()

    user_id = payload.get("sub")
    if not user_id:
        return AnonymousUser()

    user = session.get(User, int(user_id))
    if not user:
        return AnonymousUser()

    return user


def require_user(request: Request, current_user: User | AnonymousUser = Depends(get_current_user)) -> User:
    """Dependency that ensures a user is authenticated, redirecting to login if not."""
    if not getattr(current_user, "is_authenticated", False):
        raise HTTPException(status_code=303, headers={"Location": "/auth/login"})
    return current_user


def require_role(*roles: str):
    """Dependency factory that ensures a user has one of the required roles."""
    def role_checker(user: User = Depends(require_user)):
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Permission denied")
        return user
    return role_checker
