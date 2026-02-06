from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.dependencies import get_current_user, get_db, require_user, AnonymousUser
from app.models import User, Role
from app.security import create_access_token, verify_and_update_password
from app.templating import render_template
from app.utils import flash

router = APIRouter(prefix="/auth", tags=["auth"])

@router.get("/login", response_class=HTMLResponse, name="auth.login")
def login_form(request: Request, current_user: User | AnonymousUser = Depends(get_current_user)):
    """Renders the login form."""
    if current_user.is_authenticated:
        return RedirectResponse("/", status_code=303)
    return render_template("auth/login.html", {"request": request, "current_user": current_user})

@router.post("/login", name="auth.login_post")
def login_action(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    session: Session = Depends(get_db),
):
    """Handles the login form submission and issues a JWT token."""
    user = session.query(User).filter(User.email == email.lower().strip()).first()
    if not user:
        flash(request, "Invalid credentials", "danger")
        return RedirectResponse("/auth/login", status_code=303)

    verified, new_hash = verify_and_update_password(password, user.password_hash)
    if verified:
        if new_hash:
            user.password_hash = new_hash
            session.commit()

        token = create_access_token(data={"sub": str(user.id)})
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            key=settings.AUTH_COOKIE_NAME,
            value=token,
            httponly=True,
            max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            samesite=settings.SESSION_COOKIE_SAMESITE.lower(),
            secure=settings.SESSION_COOKIE_SECURE,
        )
        # Also remove old session-based auth if present
        request.session.pop("user_id", None)
        return response
    flash(request, "Invalid credentials", "danger")
    return RedirectResponse("/auth/login", status_code=303)

@router.get("/register", response_class=HTMLResponse, name="auth.register")
def register_form(
    request: Request,
    current_user: User | AnonymousUser = Depends(require_user),
):
    """Renders the user registration form (restricted to admin/issuer)."""
    if current_user.role not in ("admin", "issuer"):
        flash(request, "Only staff can register users.", "warning")
        return RedirectResponse("/", status_code=303)
    return render_template("auth/register.html", {"request": request, "current_user": current_user})

@router.post("/register", name="auth.register_post")
def register_action(
    request: Request,
    student_code: str | None = Form(default=None),
    email: str = Form(...),
    first_name: str = Form(...),
    last_name: str = Form(...),
    role: str = Form(...),
    password: str = Form(...),
    current_user: User | AnonymousUser = Depends(require_user),
    session: Session = Depends(get_db),
):
    """Handles user registration."""
    if current_user.role not in ("admin", "issuer"):
        flash(request, "Only staff can register users.", "warning")
        return RedirectResponse("/", status_code=303)

    # Check if email exists
    existing = session.query(User).filter(User.email == email.lower().strip()).first()
    if existing:
        flash(request, "Email already registered.", "danger")
        return RedirectResponse("/auth/register", status_code=303)

    user = User(
        student_code=student_code or None,
        email=email.lower().strip(),
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        registered_method="site",
    )
    user.set_password(password)
    session.add(user)

    role_obj = session.query(Role).filter_by(name=role).first()
    if role_obj:
        user.roles.append(role_obj)

    session.commit()
    flash(request, "User registered.", "success")
    return RedirectResponse("/", status_code=303)

@router.get("/logout", name="auth.logout")
def logout(request: Request):
    """Logs out the user by clearing the JWT cookie."""
    response = RedirectResponse("/auth/login", status_code=303)
    response.delete_cookie(settings.AUTH_COOKIE_NAME)
    request.session.pop("user_id", None)
    return response
