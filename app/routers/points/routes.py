from __future__ import annotations
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db, require_user, AnonymousUser
from app.models import User, Role, PointLedger, Course
from app.templating import render_template
from app.utils import flash

router = APIRouter(prefix="/points", tags=["points"])

@router.get("/adjust", response_class=HTMLResponse, name="points.adjust")
def adjust_form(
    request: Request,
    current_user: User | AnonymousUser = Depends(require_user),
    session: Session = Depends(get_db),
):
    students = (
        session.query(User)
        .join(User.roles)
        .filter(Role.name == "student")
        .order_by(User.last_name)
        .all()
    )
    courses = session.query(Course).order_by(Course.year.desc()).all()
    return render_template(
        "points/adjust.html",
        {
            "request": request,
            "students": students,
            "courses": courses,
            "current_user": current_user,
        },
    )

@router.post("/adjust", name="points.adjust_post")
def adjust_action(
    request: Request,
    user_id: int = Form(...),
    delta: int = Form(...),
    reason: str = Form(...),
    course_id: int = Form(0),
    current_user: User | AnonymousUser = Depends(require_user),
    session: Session = Depends(get_db),
):
    actual_course_id = None if course_id == 0 else course_id
    entry = PointLedger(
        user_id=user_id,
        delta=delta,
        reason=reason.strip(),
        source="manual",
        course_id=actual_course_id,
        issued_by_id=current_user.id
    )
    session.add(entry)
    session.commit()
    flash(request, "Points updated.", "success")
    return RedirectResponse("/", status_code=303)
