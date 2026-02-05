from typing import Any
from fastapi import Depends, HTTPException, Request
from .extensions import db
from .models import User


class AnonymousUser:
    is_authenticated = False
    role = "anonymous"
    first_name = "Guest"


def get_db() -> Any:
    try:
        yield db.session
    finally:
        db.remove_session()


def get_current_user(request: Request, session=Depends(get_db)) -> User | AnonymousUser:
    user_id = request.session.get("user_id")
    if not user_id:
        return AnonymousUser()
    user = session.get(User, user_id)
    if not user:
        return AnonymousUser()
    return user


def require_user(request: Request, current_user: User | AnonymousUser = Depends(get_current_user)) -> User:
    if not getattr(current_user, "is_authenticated", False):
        raise HTTPException(status_code=303, headers={"Location": "/auth/login"})
    return current_user


def require_role(*roles: str):
    def role_checker(user: User = Depends(require_user)):
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Permission denied")
        return user
    return role_checker
