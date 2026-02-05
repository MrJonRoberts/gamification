from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db, require_user, AnonymousUser
from app.models import User
from app.templating import render_template
from app.utils import flash

router = APIRouter(prefix="/auth", tags=["auth"])

@router.get("/login", response_class=HTMLResponse, name="auth.login")
def login_form(request: Request, current_user: User | AnonymousUser = Depends(get_current_user)):
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
    user = session.query(User).filter(User.email == email.lower().strip()).first()
    if user and user.check_password(password):
        request.session["user_id"] = user.id
        return RedirectResponse("/", status_code=303)
    flash(request, "Invalid credentials", "danger")
    return RedirectResponse("/auth/login", status_code=303)

@router.get("/register", response_class=HTMLResponse, name="auth.register")
def register_form(
    request: Request,
    current_user: User | AnonymousUser = Depends(require_user),
):
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
        role=role,
        registered_method="site",
    )
    user.set_password(password)
    session.add(user)
    session.commit()
    flash(request, "User registered.", "success")
    return RedirectResponse("/", status_code=303)

@router.get("/logout", name="auth.logout")
def logout(request: Request):
    request.session.pop("user_id", None)
    return RedirectResponse("/auth/login", status_code=303)
