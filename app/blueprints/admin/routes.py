from __future__ import annotations
import os, sys, runpy, importlib.util, secrets
from typing import List, Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import or_, func
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db, require_user, AnonymousUser
from app.models import User
from app.models.user import Role, Group
from app.templating import render_template
from app.utils import flash
from app.config import settings

router = APIRouter(prefix="/admin", tags=["admin"])

def admin_required(user: User = Depends(require_user)):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user

def paginate(query, page, per_page):
    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()
    pages = (total + per_page - 1) // per_page
    return type('Pagination', (), {
        "items": items,
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": pages,
        "has_prev": page > 1,
        "has_next": page < pages,
        "prev_num": page - 1,
        "next_num": page + 1,
        "iter_pages": lambda: range(1, pages + 1)
    })

def _load_and_run_seed():
    seed_path = os.path.join(settings.ROOT_PATH, "seeds/seed.py")
    if not os.path.exists(seed_path):
        raise RuntimeError(f"seed.py not found at {seed_path}")

    if settings.ROOT_PATH not in sys.path:
        sys.path.insert(0, settings.ROOT_PATH)

    spec = importlib.util.spec_from_file_location("seed", seed_path)
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    if hasattr(seed, "main") and callable(seed.main):
        seed.main()
    else:
        runpy.run_path(seed_path, run_name="__main__")

@router.get("/db-tools", response_class=HTMLResponse, name="admin.db_tools")
def db_tools(
    request: Request,
    current_user: User = Depends(admin_required),
):
    return render_template("admin/db_tools.html", {"request": request, "db_uri": settings.SQLALCHEMY_DATABASE_URI, "current_user": current_user})

@router.post("/db-tools/reset-seed", name="admin.reset_seed")
def reset_seed(
    request: Request,
    confirm_text: str = Form(...),
    clean_icons: bool = Form(False),
    current_user: User = Depends(admin_required),
):
    if confirm_text.strip().upper() != "RESET":
        flash(request, 'Type "RESET" to confirm.', "warning")
        return RedirectResponse("/admin/db-tools", status_code=303)

    if clean_icons:
        icons_dir = os.path.join(settings.ROOT_PATH, "app", "static", "icons")
        if os.path.isdir(icons_dir):
            for name in os.listdir(icons_dir):
                p = os.path.join(icons_dir, name)
                if os.path.isfile(p) and not name.startswith("."):
                    try:
                        os.remove(p)
                    except OSError:
                        pass

    try:
        _load_and_run_seed()
    except Exception as e:
        flash(request, f"Reset failed: {e}", "danger")
        return RedirectResponse("/admin/db-tools", status_code=303)

    request.session.pop("user_id", None)
    flash(request, "Database reset & seed complete. Please log in with the seeded admin.", "success")
    return RedirectResponse("/auth/login", status_code=303)

@router.get("/users", response_class=HTMLResponse, name="admin.users_index")
def users_index(
    request: Request,
    q: str = "",
    role: str = "",
    group: str = "",
    page: int = 1,
    current_user: User = Depends(admin_required),
    session: Session = Depends(get_db),
):
    per_page = 15
    query = session.query(User)

    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                User.email.ilike(like),
                User.first_name.ilike(like),
                User.last_name.ilike(like),
                User.student_code.ilike(like),
            )
        )

    if role:
        query = query.join(User.roles).filter(Role.name == role)

    if group:
        query = query.join(User.groups).filter(Group.name == group)

    query = query.order_by(User.created_at.desc())
    pagination = paginate(query, page, per_page)

    roles = session.query(Role).order_by(Role.name.asc()).all()
    groups = session.query(Group).order_by(Group.name.asc()).all()

    return render_template(
        "admin/users/index.html",
        {
            "request": request,
            "users": pagination.items,
            "pagination": pagination,
            "q": q,
            "role": role,
            "group": group,
            "roles": roles,
            "groups": groups,
            "current_user": current_user,
        }
    )

@router.get("/users/{user_id}/edit", response_class=HTMLResponse, name="admin.users_edit")
def users_edit_form(
    user_id: int,
    request: Request,
    current_user: User = Depends(admin_required),
    session: Session = Depends(get_db),
):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    roles = session.query(Role).order_by(Role.name).all()
    groups = session.query(Group).order_by(Group.name).all()

    return render_template(
        "admin/users/edit.html",
        {
            "request": request,
            "u": user,
            "roles": roles,
            "groups": groups,
            "current_user": current_user,
        }
    )

@router.post("/users/{user_id}/edit", name="admin.users_edit_post")
def users_edit_action(
    user_id: int,
    request: Request,
    first_name: str = Form(...),
    last_name: str = Form(...),
    email: str = Form(...),
    student_code: str = Form(None),
    is_active: bool = Form(True),
    registration_method: str = Form("site"),
    role_ids: List[int] = Form([], alias="roles"),
    group_ids: List[int] = Form([], alias="groups"),
    current_user: User = Depends(admin_required),
    session: Session = Depends(get_db),
):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.first_name = first_name.strip()
    user.last_name = last_name.strip()
    user.email = email.strip().lower()
    user.student_code = (student_code or "").strip() or None
    user.is_active = is_active
    user.registered_method = registration_method

    if role_ids:
        user.roles = session.query(Role).filter(Role.id.in_(role_ids)).all()
    else:
        user.roles = []

    if group_ids:
        user.groups = session.query(Group).filter(Group.id.in_(group_ids)).all()
    else:
        user.groups = []

    session.commit()
    flash(request, "User updated.", "success")
    return RedirectResponse("/admin/users", status_code=303)

@router.post("/users/{user_id}/toggle", name="admin.users_toggle_active")
def users_toggle_active(
    user_id: int,
    request: Request,
    current_user: User = Depends(admin_required),
    session: Session = Depends(get_db),
):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = not user.is_active
    session.commit()
    flash(request, f"User {'activated' if user.is_active else 'deactivated'}.", "success")
    return RedirectResponse(request.headers.get("referer", "/admin/users"), status_code=303)

@router.post("/users/{user_id}/reset-password", name="admin.users_reset_password")
def users_reset_password(
    user_id: int,
    request: Request,
    current_user: User = Depends(admin_required),
    session: Session = Depends(get_db),
):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    new_password = secrets.token_urlsafe(10)
    user.set_password(new_password)
    session.commit()
    flash(request, f"Temporary password set: {new_password}", "warning")
    return RedirectResponse(request.headers.get("referer", "/admin/users"), status_code=303)

@router.post("/users/{user_id}/delete", name="admin.users_delete")
def users_delete(
    user_id: int,
    request: Request,
    current_user: User = Depends(admin_required),
    session: Session = Depends(get_db),
):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    session.delete(user)
    session.commit()
    flash(request, "User deleted.", "success")
    return RedirectResponse("/admin/users", status_code=303)
