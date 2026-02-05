from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Request, Body
from fastapi.responses import JSONResponse, HTMLResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db, require_user, AnonymousUser
from app.models import Course, User, Behaviour, SeatingPosition
from app.templating import render_template

router = APIRouter(prefix="/courses", tags=["seating"])

def _is_enrolled(course: Course, user: User) -> bool:
    return any(u.id == user.id for u in course.students)

def _can_manage(user: User | AnonymousUser) -> bool:
    return getattr(user, "role", "") in {"admin", "issuer"}

@router.get("/{course_id}/seating", response_class=HTMLResponse, name="seating.seating_view")
def seating_view(
    course_id: int,
    request: Request,
    current_user: User | AnonymousUser = Depends(require_user),
    session: Session = Depends(get_db),
):
    course = session.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    if not _can_manage(current_user):
        raise HTTPException(status_code=403, detail="Permission denied")

    users = sorted(course.students, key=lambda s: (s.last_name.lower(), s.first_name.lower()))

    pos_map = {
        p.user_id: p
        for p in session.query(SeatingPosition).filter_by(course_id=course.id).all()
    }

    totals = dict(
        session.query(Behaviour.user_id, func.coalesce(func.sum(Behaviour.delta), 0))
        .filter(Behaviour.course_id == course.id)
        .group_by(Behaviour.user_id)
        .all()
    )

    return render_template(
        "courses/seating.html",
        {
            "request": request,
            "course": course,
            "users": users,
            "pos_map": pos_map,
            "totals": totals,
            "current_user": current_user,
        }
    )

@router.get("/{course_id}/api/seating", name="seating.api_all_positions")
def api_all_positions(
    course_id: int,
    session: Session = Depends(get_db),
    current_user: User | AnonymousUser = Depends(require_user),
):
    course = session.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    rows = session.query(SeatingPosition).filter_by(course_id=course_id).all()
    return [{"user_id": r.user_id, "x": r.x, "y": r.y, "locked": r.locked} for r in rows]

@router.post("/{course_id}/api/seating/{user_id}", name="seating.api_update_position")
def api_update_position(
    course_id: int,
    user_id: int,
    data: dict = Body(...),
    session: Session = Depends(get_db),
    current_user: User | AnonymousUser = Depends(require_user),
):
    course = session.get(Course, course_id)
    user = session.get(User, user_id)
    if not course or not user:
        raise HTTPException(status_code=404, detail="Course or User not found")

    if not _can_manage(current_user) or not _is_enrolled(course, user):
        raise HTTPException(status_code=403, detail="Permission denied")

    x = float(data.get("x", 0))
    y = float(data.get("y", 0))
    locked = data.get("locked")

    sp = session.query(SeatingPosition).filter_by(course_id=course_id, user_id=user_id).first()
    if not sp:
        sp = SeatingPosition(course_id=course_id, user_id=user_id, x=x, y=y)
        session.add(sp)
    else:
        if sp.locked and data.get("drag", False):
            return {"ok": True, "ignored": "locked"}
        sp.x, sp.y = x, y

    if locked is not None:
        sp.locked = bool(locked)

    session.commit()
    return {"ok": True}

@router.post("/{course_id}/api/seating/bulk_lock", name="seating.api_bulk_lock")
def api_bulk_lock(
    course_id: int,
    data: dict = Body(...),
    session: Session = Depends(get_db),
    current_user: User | AnonymousUser = Depends(require_user),
):
    course = session.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    if not _can_manage(current_user):
        raise HTTPException(status_code=403, detail="Permission denied")

    locked = bool(data.get("locked", True))
    session.query(SeatingPosition).filter_by(course_id=course_id).update({"locked": locked})
    session.commit()
    return {"ok": True}

@router.post("/{course_id}/api/behaviour/{user_id}/adjust", name="seating.api_behaviour_adjust")
def api_behaviour_adjust(
    course_id: int,
    user_id: int,
    data: dict = Body(...),
    session: Session = Depends(get_db),
    current_user: User | AnonymousUser = Depends(require_user),
):
    course = session.get(Course, course_id)
    user = session.get(User, user_id)
    if not course or not user:
        raise HTTPException(status_code=404, detail="Course or User not found")

    if not _can_manage(current_user) or not _is_enrolled(course, user):
        raise HTTPException(status_code=403, detail="Permission denied")

    delta = int(data.get("delta", 0))
    note = (data.get("note") or "").strip()
    if delta == 0:
        return JSONResponse({"ok": False, "error": "delta required"}, status_code=400)

    b = Behaviour(
        user_id=user_id,
        course_id=course_id,
        delta=delta,
        note=note or None,
        created_by_id=current_user.id,
    )
    try:
        session.add(b)
        session.commit()
    except Exception as e:
        session.rollback()
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    total = session.query(func.coalesce(func.sum(Behaviour.delta), 0))\
        .filter(Behaviour.user_id == user_id, Behaviour.course_id == course_id)\
        .scalar() or 0

    return {"ok": True, "total": int(total)}
