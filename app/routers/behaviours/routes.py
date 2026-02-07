from __future__ import annotations
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, HTMLResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.dependencies import get_db, require_user, AnonymousUser
from app.models import Behaviour, PointLedger, User, Course
from app.templating import render_template

router = APIRouter(prefix="/behaviours", tags=["behaviours"])

def _staff_only(user: User | AnonymousUser) -> bool:
    return getattr(user, "is_authenticated", False) and getattr(user, "role", "") in {"admin", "issuer"}

@router.post("/add")
def add_behaviour(
    request: Request,
    user_id: int = Form(...),
    delta: int = Form(...),
    note: str = Form(None),
    course_id: int = Form(None),
    current_user: User | AnonymousUser = Depends(require_user),
    session: Session = Depends(get_db),
):
    if not _staff_only(current_user):
        return JSONResponse({"ok": False, "error": "Permission denied"}, status_code=403)

    if not user_id or delta == 0:
        return JSONResponse({"ok": False, "error": "Student and non-zero points are required"}, status_code=400)

    user = session.get(User, user_id)
    if not user or user.role != "student":
        return JSONResponse({"ok": False, "error": "Student not found"}, status_code=404)

    course = session.get(Course, course_id) if course_id else None

    try:
        b = Behaviour(
            user_id=user.id,
            course_id=course.id if course else None,
            delta=delta,
            note=note.strip() if note else None,
            created_by_id=current_user.id,
        )
        session.add(b)

        session.add(PointLedger(
            user_id=user.id,
            delta=delta,
            reason=f"Behaviour: {note[:120]}" if note else "Behaviour",
            source="behaviour",
            issued_by_id=current_user.id,
        ))

        session.commit()
        return JSONResponse({"ok": True})
    except Exception:
        session.rollback()
        return JSONResponse({"ok": False, "error": "Server error"}, status_code=500)

@router.get("/list")
def list_behaviours(
    request: Request,
    user_id: int,
    course_id: int = None,
    current_user: User | AnonymousUser = Depends(require_user),
    session: Session = Depends(get_db),
):
    student = session.get(User, user_id)
    if not student or student.role != "student":
        return HTMLResponse('<div class="text-muted">Student not found.</div>', status_code=404)

    # Base query
    base = session.query(Behaviour).filter(Behaviour.user_id == user_id)
    if course_id:
        base = base.filter(Behaviour.course_id == course_id)

    behaviours = (
        base.order_by(Behaviour.created_at.desc(), Behaviour.id.desc())
            .limit(50)
            .all()
    )

    # Totals
    total_query = session.query(func.coalesce(func.sum(Behaviour.delta), 0)).filter(Behaviour.user_id == user_id)
    if course_id:
        total_query = total_query.filter(Behaviour.course_id == course_id)

    total_all = total_query.scalar() or 0
    total_shown = sum((b.delta or 0) for b in behaviours)

    return render_template(
        "behaviours/_list.html",
        {
            "request": request,
            "behaviours": behaviours,
            "total_all": int(total_all),
            "total_shown": int(total_shown),
        }
    )
