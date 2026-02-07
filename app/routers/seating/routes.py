from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request, Body
from fastapi.responses import JSONResponse, HTMLResponse
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.dependencies import get_db, require_user, AnonymousUser
from app.models import Course, User, Behaviour, SeatingPosition, SeatingLayout
from app.templating import render_template

router = APIRouter(prefix="/courses", tags=["seating"])


def _is_enrolled(course: Course, user: User) -> bool:
    return any(u.id == user.id for u in course.students)


def _can_manage(user: User | AnonymousUser) -> bool:
    return getattr(user, "role", "") in {"admin", "issuer"}


def _require_manage_access(session: Session, course_id: int, user: User | AnonymousUser) -> Course:
    course = session.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    if not _can_manage(user):
        raise HTTPException(status_code=403, detail="Permission denied")
    return course


def _as_position_payload(row: SeatingPosition) -> dict:
    return {"user_id": row.user_id, "x": row.x, "y": row.y, "locked": row.locked}


def _ensure_layout_table(session: Session) -> None:
    SeatingLayout.__table__.create(bind=session.get_bind(), checkfirst=True)


@router.get("/{course_id}/seating", response_class=HTMLResponse, name="seating.seating_view")
def seating_view(
    course_id: int,
    request: Request,
    current_user: User | AnonymousUser = Depends(require_user),
    session: Session = Depends(get_db),
):
    course = _require_manage_access(session, course_id, current_user)
    _ensure_layout_table(session)

    users = sorted(course.students, key=lambda s: (s.last_name.lower(), s.first_name.lower()))
    pos_map = {p.user_id: p for p in session.query(SeatingPosition).filter_by(course_id=course.id).all()}
    totals = dict(
        session.query(Behaviour.user_id, func.coalesce(func.sum(Behaviour.delta), 0))
        .filter(Behaviour.course_id == course.id)
        .group_by(Behaviour.user_id)
        .all()
    )
    layouts = (
        session.query(SeatingLayout)
        .filter_by(course_id=course.id)
        .order_by(SeatingLayout.name.asc())
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
            "layouts": layouts,
            "current_user": current_user,
        },
    )


@router.get("/{course_id}/api/seating", name="seating.api_all_positions")
def api_all_positions(
    course_id: int,
    session: Session = Depends(get_db),
    current_user: User | AnonymousUser = Depends(require_user),
):
    _require_manage_access(session, course_id, current_user)
    rows = session.query(SeatingPosition).filter_by(course_id=course_id).all()
    return [_as_position_payload(r) for r in rows]


@router.post("/{course_id}/api/seating/students/{user_id}", name="seating.api_update_position")
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

    try:
        x = float(data.get("x", 0))
        y = float(data.get("y", 0))
    except (TypeError, ValueError):
        return JSONResponse({"ok": False, "error": "Invalid x/y coordinates"}, status_code=400)

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
    _require_manage_access(session, course_id, current_user)
    locked = bool(data.get("locked", True))
    session.query(SeatingPosition).filter_by(course_id=course_id).update({"locked": locked})
    session.commit()
    return {"ok": True}


@router.get("/{course_id}/api/seating/layouts", name="seating.api_layouts_list")
def api_layouts_list(
    course_id: int,
    session: Session = Depends(get_db),
    current_user: User | AnonymousUser = Depends(require_user),
):
    _require_manage_access(session, course_id, current_user)
    _ensure_layout_table(session)
    layouts = (
        session.query(SeatingLayout)
        .filter_by(course_id=course_id)
        .order_by(SeatingLayout.name.asc())
        .all()
    )
    return [
        {
            "id": layout.id,
            "name": layout.name,
            "updated_at": layout.updated_at.isoformat() if layout.updated_at else None,
        }
        for layout in layouts
    ]


@router.post("/{course_id}/api/seating/layouts", name="seating.api_layouts_save")
def api_layouts_save(
    course_id: int,
    data: dict = Body(...),
    session: Session = Depends(get_db),
    current_user: User | AnonymousUser = Depends(require_user),
):
    course = _require_manage_access(session, course_id, current_user)
    _ensure_layout_table(session)

    name = (data.get("name") or "").strip()
    overwrite = bool(data.get("overwrite", False))
    if not name:
        return JSONResponse({"ok": False, "error": "Layout name is required"}, status_code=400)

    positions = session.query(SeatingPosition).filter_by(course_id=course.id).all()
    serialized = json.dumps([_as_position_payload(p) for p in positions])

    layout = session.query(SeatingLayout).filter_by(course_id=course.id, name=name).first()
    if layout and not overwrite:
        return JSONResponse({"ok": False, "error": "Layout name already exists"}, status_code=409)

    if not layout:
        layout = SeatingLayout(course_id=course.id, name=name, data=serialized)
        session.add(layout)
    else:
        layout.data = serialized

    try:
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)

    return {"ok": True, "id": layout.id, "name": layout.name}


@router.post("/{course_id}/api/seating/layouts/{layout_id}/load", name="seating.api_layouts_load")
def api_layouts_load(
    course_id: int,
    layout_id: int,
    session: Session = Depends(get_db),
    current_user: User | AnonymousUser = Depends(require_user),
):
    course = _require_manage_access(session, course_id, current_user)
    _ensure_layout_table(session)

    layout = session.query(SeatingLayout).filter_by(course_id=course.id, id=layout_id).first()
    if not layout:
        raise HTTPException(status_code=404, detail="Layout not found")

    try:
        payload = json.loads(layout.data or "[]")
    except json.JSONDecodeError:
        return JSONResponse({"ok": False, "error": "Layout data is invalid"}, status_code=500)

    enrolled_ids = {student.id for student in course.students}
    position_by_user = {
        pos.user_id: pos for pos in session.query(SeatingPosition).filter_by(course_id=course.id).all()
    }

    for item in payload:
        user_id = item.get("user_id")
        if user_id not in enrolled_ids:
            continue

        try:
            x = float(item.get("x", 0))
            y = float(item.get("y", 0))
        except (TypeError, ValueError):
            continue

        locked = bool(item.get("locked", False))
        row = position_by_user.get(user_id)
        if row is None:
            row = SeatingPosition(course_id=course.id, user_id=user_id)
            session.add(row)
            position_by_user[user_id] = row

        row.x = x
        row.y = y
        row.locked = locked

    session.commit()
    return {"ok": True, "positions": [_as_position_payload(row) for row in position_by_user.values()]}


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
    except Exception as exc:
        session.rollback()
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)

    total = (
        session.query(func.coalesce(func.sum(Behaviour.delta), 0))
        .filter(Behaviour.user_id == user_id, Behaviour.course_id == course_id)
        .scalar()
        or 0
    )

    return {"ok": True, "total": int(total)}
