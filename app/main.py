from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.extensions import db
from app.models import PointLedger, User
from sqlalchemy import func


class AnonymousUser:
    is_authenticated = False
    role = "anonymous"
    first_name = "Guest"


templates = Jinja2Templates(directory="app/templates")


def _url_for(request: Request, name: str, **params: Any) -> str:
    if name == "static":
        path = params.get("filename", "")
        return request.url_for("static", path=path)
    try:
        return request.app.url_path_for(name, **params)
    except Exception:
        return "#"


def _flash(request: Request, message: str, category: str = "info") -> None:
    messages = request.session.setdefault("_flashes", [])
    messages.append((category, message))
    request.session["_flashes"] = messages


def _get_flashed_messages(request: Request, with_categories: bool = True) -> list[Any]:
    messages = request.session.pop("_flashes", [])
    if not with_categories:
        return [message for _, message in messages]
    return messages


def _csrf_token() -> str:
    return ""


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


def create_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.SECRET_KEY,
        same_site=settings.SESSION_COOKIE_SAMESITE,
        https_only=settings.SESSION_COOKIE_SECURE,
    )

    app.mount("/static", StaticFiles(directory="app/static"), name="static")

    templates.env.globals["csrf_token"] = _csrf_token

    @app.get("/", response_class=HTMLResponse, name="main.index")
    def index(
        request: Request,
        current_user: User | AnonymousUser = Depends(require_user),
        session=Depends(get_db),
    ):
        rows = session.execute(
            db.select(
                User.id,
                User.first_name,
                User.last_name,
                func.coalesce(func.sum(PointLedger.delta), 0).label("points"),
            )
            .outerjoin(PointLedger, PointLedger.user_id == User.id)
            .where(User.role == "student")
            .group_by(User.id)
            .order_by(func.sum(PointLedger.delta).desc())
            .limit(20)
        ).all()
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "leaderboard": rows,
                "current_user": current_user,
                "config": settings,
                "url_for": lambda name, **params: _url_for(request, name, **params),
                "get_flashed_messages": lambda with_categories=True: _get_flashed_messages(
                    request, with_categories=with_categories
                ),
            },
        )

    @app.get("/timer", response_class=HTMLResponse, name="main.timer")
    def timer(request: Request, current_user: User | AnonymousUser = Depends(require_user)):
        return templates.TemplateResponse(
            "timer.html",
            {
                "request": request,
                "current_user": current_user,
                "config": settings,
                "url_for": lambda name, **params: _url_for(request, name, **params),
                "get_flashed_messages": lambda with_categories=True: _get_flashed_messages(
                    request, with_categories=with_categories
                ),
            },
        )

    @app.get("/auth/login", response_class=HTMLResponse, name="auth.login")
    def login_form(request: Request, current_user: User | AnonymousUser = Depends(get_current_user)):
        if current_user.is_authenticated:
            return RedirectResponse("/", status_code=303)
        return templates.TemplateResponse(
            "auth/login.html",
            {
                "request": request,
                "current_user": current_user,
                "config": settings,
                "url_for": lambda name, **params: _url_for(request, name, **params),
                "get_flashed_messages": lambda with_categories=True: _get_flashed_messages(
                    request, with_categories=with_categories
                ),
            },
        )

    @app.post("/auth/login", name="auth.login_post")
    def login_action(
        request: Request,
        email: str = Form(...),
        password: str = Form(...),
        session=Depends(get_db),
    ):
        user = session.query(User).filter(User.email == email.lower().strip()).first()
        if user and user.check_password(password):
            request.session["user_id"] = user.id
            return RedirectResponse("/", status_code=303)
        _flash(request, "Invalid credentials", "danger")
        return RedirectResponse("/auth/login", status_code=303)

    @app.get("/auth/register", response_class=HTMLResponse, name="auth.register")
    def register_form(
        request: Request,
        current_user: User | AnonymousUser = Depends(require_user),
    ):
        if current_user.role not in ("admin", "issuer"):
            _flash(request, "Only staff can register users.", "warning")
            return RedirectResponse("/", status_code=303)
        return templates.TemplateResponse(
            "auth/register.html",
            {
                "request": request,
                "current_user": current_user,
                "config": settings,
                "url_for": lambda name, **params: _url_for(request, name, **params),
                "get_flashed_messages": lambda with_categories=True: _get_flashed_messages(
                    request, with_categories=with_categories
                ),
            },
        )

    @app.post("/auth/register", name="auth.register_post")
    def register_action(
        request: Request,
        student_code: str | None = Form(default=None),
        email: str = Form(...),
        first_name: str = Form(...),
        last_name: str = Form(...),
        role: str = Form(...),
        password: str = Form(...),
        current_user: User | AnonymousUser = Depends(require_user),
        session=Depends(get_db),
    ):
        if current_user.role not in ("admin", "issuer"):
            _flash(request, "Only staff can register users.", "warning")
            return RedirectResponse("/", status_code=303)
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
        _flash(request, "User registered.", "success")
        return RedirectResponse("/", status_code=303)

    @app.get("/auth/logout", name="auth.logout")
    def logout(request: Request):
        request.session.pop("user_id", None)
        return RedirectResponse("/auth/login", status_code=303)

    @app.get("/students/", response_class=HTMLResponse, name="students.list_students")
    def students_placeholder(request: Request, current_user: User | AnonymousUser = Depends(require_user)):
        return templates.TemplateResponse(
            "not_implemented.html",
            {
                "request": request,
                "current_user": current_user,
                "config": settings,
                "feature": "Students",
                "url_for": lambda name, **params: _url_for(request, name, **params),
                "get_flashed_messages": lambda with_categories=True: _get_flashed_messages(
                    request, with_categories=with_categories
                ),
            },
        )

    @app.get("/courses/", response_class=HTMLResponse, name="courses.list_courses")
    def courses_placeholder(request: Request, current_user: User | AnonymousUser = Depends(require_user)):
        return templates.TemplateResponse(
            "not_implemented.html",
            {
                "request": request,
                "current_user": current_user,
                "config": settings,
                "feature": "Courses",
                "url_for": lambda name, **params: _url_for(request, name, **params),
                "get_flashed_messages": lambda with_categories=True: _get_flashed_messages(
                    request, with_categories=with_categories
                ),
            },
        )

    @app.get("/badges/", response_class=HTMLResponse, name="badges.list_badges")
    def badges_placeholder(request: Request, current_user: User | AnonymousUser = Depends(require_user)):
        return templates.TemplateResponse(
            "not_implemented.html",
            {
                "request": request,
                "current_user": current_user,
                "config": settings,
                "feature": "Badges",
                "url_for": lambda name, **params: _url_for(request, name, **params),
                "get_flashed_messages": lambda with_categories=True: _get_flashed_messages(
                    request, with_categories=with_categories
                ),
            },
        )

    @app.get("/awards/", response_class=HTMLResponse, name="awards.list_awards")
    def awards_placeholder(request: Request, current_user: User | AnonymousUser = Depends(require_user)):
        return templates.TemplateResponse(
            "not_implemented.html",
            {
                "request": request,
                "current_user": current_user,
                "config": settings,
                "feature": "Awards",
                "url_for": lambda name, **params: _url_for(request, name, **params),
                "get_flashed_messages": lambda with_categories=True: _get_flashed_messages(
                    request, with_categories=with_categories
                ),
            },
        )

    @app.get("/points/adjust", response_class=HTMLResponse, name="points.adjust")
    def points_placeholder(request: Request, current_user: User | AnonymousUser = Depends(require_user)):
        return templates.TemplateResponse(
            "not_implemented.html",
            {
                "request": request,
                "current_user": current_user,
                "config": settings,
                "feature": "Points",
                "url_for": lambda name, **params: _url_for(request, name, **params),
                "get_flashed_messages": lambda with_categories=True: _get_flashed_messages(
                    request, with_categories=with_categories
                ),
            },
        )

    @app.get("/admin/users", response_class=HTMLResponse, name="admin.users_index")
    def admin_users_placeholder(request: Request, current_user: User | AnonymousUser = Depends(require_user)):
        return templates.TemplateResponse(
            "not_implemented.html",
            {
                "request": request,
                "current_user": current_user,
                "config": settings,
                "feature": "Admin Users",
                "url_for": lambda name, **params: _url_for(request, name, **params),
                "get_flashed_messages": lambda with_categories=True: _get_flashed_messages(
                    request, with_categories=with_categories
                ),
            },
        )

    return app


app = create_app()
