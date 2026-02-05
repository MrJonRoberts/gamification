from __future__ import annotations
from datetime import datetime, timedelta, date
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Body
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy import func
from sqlalchemy.orm import Session
from typing import List, Optional

from app.dependencies import get_current_user, get_db, require_user, AnonymousUser
from app.extensions import db
from app.models import Course, Lesson, User, Attendance, Enrollment, AttendanceStatus
from app.services.attendance_service import ensure_attendance_rows, set_no_class_for_lesson
from app.services.orm_utils import first_model_attribute
from app.templating import render_template
from app.utils import flash

# Map normalized statuses -> display metadata
STATUS_META = {
    "present": {"label": "Present", "icon": "fa-circle-check", "class": "att-present"},
    "absent": {"label": "Absent", "icon": "fa-circle-xmark", "class": "att-absent"},
    "late": {"label": "Late", "icon": "fa-clock", "class": "att-late"},
    "excused": {"label": "Excused", "icon": "fa-user-check", "class": "att-excused"},
    "unknown": {"label": "—", "icon": "fa-circle-minus", "class": "att-unknown"},
}
STATUS_UI_NOT_SET = {"label": "Not set", "icon": "fa-circle-minus", "class": "att-NOT_SET"}

def _to_enum(code: str):
    if not code:
        return None
    s = code.strip().upper()
    if s == "EXCUSED":
        s = "SCHOOL_APPROVED_ABSENT"
    # Map back to enum values
    valid = {e.value for e in AttendanceStatus}
    if s in valid:
        return s
    return None

def _parse_selected_date(request: Request):
    qs = request.query_params.get("date", "").strip()
    if qs:
        try:
            return datetime.strptime(qs, "%Y-%m-%d").date()
        except ValueError:
            pass
    return date.today()

router = APIRouter(prefix="/courses", tags=["attendance"])

@router.get("/{course_id}/lessons", response_class=HTMLResponse, name="attendance.course_lessons")
def course_lessons(
    course_id: int,
    request: Request,
    current_user: User | AnonymousUser = Depends(require_user),
    session: Session = Depends(get_db),
):
    course = session.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    lessons = (session.query(Lesson)
               .filter_by(course_id=course.id)
               .order_by(Lesson.date.asc())
               .all())
    return render_template("attendance/course_lessons.html", {"request": request, "course": course, "lessons": lessons, "current_user": current_user})

@router.get("/{course_id}/lessons/{lesson_id}/roll", response_class=HTMLResponse, name="attendance.roll")
def roll_form(
    course_id: int,
    lesson_id: int,
    request: Request,
    current_user: User | AnonymousUser = Depends(require_user),
    session: Session = Depends(get_db),
):
    course = session.get(Course, course_id)
    lesson = session.get(Lesson, lesson_id)
    if not course or not lesson:
        raise HTTPException(status_code=404, detail="Course or Lesson not found")
    if lesson.course_id != course.id:
        flash(request, "Lesson does not belong to this course.", "danger")
        return RedirectResponse(f"/courses/{course_id}/lessons", status_code=303)

    attendance_by_student = ensure_attendance_rows(course, lesson)
    return render_template(
        "attendance/roll.html",
        {
            "request": request,
            "course": course,
            "lesson": lesson,
            "attendance_by_student": attendance_by_student,
            "students": course.students,
            "current_user": current_user,
        }
    )

@router.post("/{course_id}/lessons/{lesson_id}/roll", name="attendance.roll_post")
async def roll_action(
    course_id: int,
    lesson_id: int,
    request: Request,
    current_user: User | AnonymousUser = Depends(require_user),
    session: Session = Depends(get_db),
):
    course = session.get(Course, course_id)
    lesson = session.get(Lesson, lesson_id)
    if not course or not lesson:
        raise HTTPException(status_code=404, detail="Course or Lesson not found")

    form_data = await request.form()
    toggle = form_data.get("toggle_cancel")
    if toggle:
        set_no_class_for_lesson(lesson, on=(toggle == "on"))
        flash(request, "Lesson updated.", "success")
        return RedirectResponse(f"/courses/{course_id}/lessons/{lesson_id}/roll", status_code=303)

    attendance_by_student = ensure_attendance_rows(course, lesson)
    changed = 0
    for student in course.students:
        status_field = f"status_{student.id}"
        comment_field = f"comment_{student.id}"
        if status_field in form_data:
            a = attendance_by_student[student.id]
            new_status = form_data.get(status_field)
            new_comment = form_data.get(comment_field, "")[:255] or None
            # Validate status
            if new_status in {s.value for s in AttendanceStatus}:
                a.status = new_status
                a.comment = new_comment
                a.marked_by_user_id = getattr(current_user, "id", None)
                changed += 1
    if changed:
        session.commit()
        flash(request, f"Saved roll for {changed} students.", "success")
    else:
        flash(request, "No changes.", "info")
    return RedirectResponse(f"/courses/{course_id}/lessons/{lesson_id}/roll", status_code=303)

@router.get("/{course_id}/attendance", response_class=HTMLResponse, name="attendance.course_attendance")
def course_attendance(
    course_id: int,
    request: Request,
    current_user: User | AnonymousUser = Depends(require_user),
    session: Session = Depends(get_db),
):
    course = session.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    selected_date = _parse_selected_date(request)

    lessons_q = session.query(Lesson).filter(Lesson.course_id == course.id)
    lesson_date_col = first_model_attribute(Lesson, ["date"])
    lesson_time_col = first_model_attribute(Lesson, ["start_time", "starts_at"])
    if lesson_date_col is not None:
        lessons_q = lessons_q.filter(lesson_date_col == selected_date)
        if lesson_time_col is not None:
            lessons_q = lessons_q.order_by(lesson_date_col.asc(), lesson_time_col.asc())
        else:
            lessons_q = lessons_q.order_by(lesson_date_col.asc())
    elif lesson_time_col is not None:
        lessons_q = lessons_q.order_by(lesson_time_col.asc())
    else:
        lessons_q = lessons_q.order_by(Lesson.id.asc())

    lessons = lessons_q.all()
    lesson_ids = [l.id for l in lessons]

    students = (
        session.query(User)
        .join(Enrollment, Enrollment.c.user_id == User.id)
        .filter(Enrollment.c.course_id == course.id)
        .order_by(User.last_name.asc(), User.first_name.asc())
        .all()
    )
    student_ids = [u.id for u in students]

    att_rows = (
        session.query(Attendance)
        .join(Lesson, Lesson.id == Attendance.lesson_id)
        .filter(Lesson.course_id == course.id)
        .filter(Attendance.lesson_id.in_(lesson_ids) if lesson_ids else True)
        .filter(Attendance.student_id.in_(student_ids) if student_ids else True)
        .all()
    )
    att_map = {(a.student_id, a.lesson_id): (a.status or None) for a in att_rows}

    base = {"PRESENT": 0, "ABSENT": 0, "LATE": 0, "SCHOOL_APPROVED_ABSENT": 0, "NO_CLASS_TODAY": 0}
    counts = {lid: dict(base) for lid in lesson_ids}
    for (sid, lid), status in att_map.items():
        if status and lid in counts and status in counts[lid]:
            counts[lid][status] += 1

    def present_ratio_for(student_id: int) -> float:
        if not lesson_ids:
            return 0.0
        present_like = 0
        denom = 0
        for lid in lesson_ids:
            s = att_map.get((student_id, lid))
            if not s:
                continue
            if s == "NO_CLASS_TODAY":
                continue
            denom += 1
            if s in {"PRESENT", "LATE"}:
                present_like += 1
        return (present_like / denom) if denom else 0.0

    student_present_ratio = {u.id: present_ratio_for(u.id) for u in students}

    return render_template(
        "attendance/course_attendance.html",
        {
            "request": request,
            "course": course,
            "students": students,
            "lessons": lessons,
            "att_map": att_map,
            "status_meta": STATUS_META,
            "status_ui_not_set": STATUS_UI_NOT_SET,
            "counts": counts,
            "student_present_ratio": student_present_ratio,
            "selected_date": selected_date,
            "current_user": current_user,
        }
    )

@router.post("/{course_id}/attendance/api/set", name="attendance.api_set_attendance")
def api_set_attendance(
    course_id: int,
    data: dict = Body(...),
    session: Session = Depends(get_db),
    current_user: User | AnonymousUser = Depends(require_user),
):
    lesson_id = data.get("lesson_id")
    student_id = data.get("user_id") or data.get("student_id")
    status = _to_enum(data.get("status"))

    if not all([lesson_id, student_id, status]):
        return JSONResponse({"ok": False, "error": "Missing lesson_id, student_id, or invalid status"}, status_code=400)

    course = session.get(Course, course_id)
    lesson = session.get(Lesson, lesson_id)
    if not course or not lesson or lesson.course_id != course.id:
        return JSONResponse({"ok": False, "error": "Lesson does not belong to course"}, status_code=400)

    enrolled = session.query(Enrollment).filter(
        Enrollment.c.course_id == course.id,
        Enrollment.c.user_id == int(student_id)
    ).first()
    if not enrolled:
        return JSONResponse({"ok": False, "error": "Student not enrolled in course"}, status_code=400)

    rec = session.query(Attendance).filter_by(lesson_id=lesson_id, student_id=student_id).first()
    if not rec:
        rec = Attendance(lesson_id=lesson_id, student_id=student_id, status=status)
        session.add(rec)
    else:
        rec.status = status
    rec.marked_at = datetime.utcnow()
    rec.marked_by_user_id = getattr(current_user, "id", None)
    session.commit()
    return {"ok": True}

@router.post("/{course_id}/attendance/api/bulk_set", name="attendance.api_bulk_set_attendance")
def api_bulk_set_attendance(
    course_id: int,
    data: dict = Body(...),
    session: Session = Depends(get_db),
    current_user: User | AnonymousUser = Depends(require_user),
):
    status = _to_enum(data.get("status"))
    if not status:
        return JSONResponse({"ok": False, "error": "Invalid status"}, status_code=400)

    lesson_id = data.get("lesson_id")
    lesson_ids = data.get("lesson_ids") or []
    targets = []
    if lesson_id:
        targets.append(int(lesson_id))
    if isinstance(lesson_ids, list):
        targets.extend([int(x) for x in lesson_ids if x is not None])

    course = session.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    valid_lids = [lid for (lid,) in session.query(Lesson.id).filter(Lesson.course_id == course.id, Lesson.id.in_(targets)).all()]
    if not valid_lids:
        return JSONResponse({"ok": False, "error": "No valid lessons for this course"}, status_code=400)

    student_ids = [uid for (uid,) in session.query(Enrollment.c.user_id).filter(Enrollment.c.course_id == course.id).all()]
    if not student_ids:
        return {"ok": True, "inserted": 0, "updated": 0}

    existing_rows = session.query(Attendance).filter(
        Attendance.lesson_id.in_(valid_lids),
        Attendance.student_id.in_(student_ids)
    ).all()
    existing = {(a.student_id, a.lesson_id): a for a in existing_rows}

    now = datetime.utcnow()
    inserted = 0
    updated = 0
    for lid in valid_lids:
        for sid in student_ids:
            key = (sid, lid)
            if key in existing:
                existing[key].status = status
                existing[key].marked_at = now
                existing[key].marked_by_user_id = getattr(current_user, "id", None)
                updated += 1
            else:
                session.add(Attendance(
                    lesson_id=lid, student_id=sid, status=status,
                    marked_at=now, marked_by_user_id=getattr(current_user, "id", None)
                ))
                inserted += 1
    session.commit()
    return {"ok": True, "inserted": inserted, "updated": updated}

@router.get("/{course_id}/attendance/api/summary", name="attendance.api_summary")
def api_summary(
    course_id: int,
    request: Request,
    session: Session = Depends(get_db),
    current_user: User | AnonymousUser = Depends(require_user),
):
    course = session.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    selected_date = _parse_selected_date(request)

    lessons_q = session.query(Lesson).filter(Lesson.course_id == course.id)
    if hasattr(Lesson, "starts_at"):
        lessons_q = lessons_q.filter(func.date(Lesson.starts_at) == selected_date)
    elif hasattr(Lesson, "date"):
        lessons_q = lessons_q.filter(Lesson.date == selected_date)

    lessons = lessons_q.all()
    lesson_ids = [l.id for l in lessons]
    if not lesson_ids:
        return {"lessons": {}, "student_ratio": {}}

    raw = session.query(
        Attendance.lesson_id,
        Attendance.status,
        func.count(Attendance.id)
    ).join(Lesson, Lesson.id == Attendance.lesson_id
    ).filter(Lesson.course_id == course.id, Attendance.lesson_id.in_(lesson_ids)
    ).group_by(Attendance.lesson_id, Attendance.status).all()

    base = {"PRESENT": 0, "ABSENT": 0, "LATE": 0, "SCHOOL_APPROVED_ABSENT": 0, "NO_CLASS_TODAY": 0}
    counts = {lid: dict(base) for lid in lesson_ids}
    for lid, status, cnt in raw:
        if status in counts[lid]:
            counts[lid][status] = int(cnt)

    student_ids = [uid for (uid,) in session.query(Enrollment.c.user_id).filter(Enrollment.c.course_id == course.id).all()]
    rows = session.query(Attendance).join(Lesson, Lesson.id == Attendance.lesson_id).filter(
        Lesson.course_id == course.id,
        Attendance.lesson_id.in_(lesson_ids),
        Attendance.student_id.in_(student_ids)
    ).all()

    by_user = {sid: [] for sid in student_ids}
    for r in rows:
        by_user[r.student_id].append(r.status)

    student_ratio = {}
    for sid in student_ids:
        statuses = by_user.get(sid, [])
        present_like = sum(1 for s in statuses if s in {"PRESENT", "LATE"})
        denom = sum(1 for s in statuses if s and s != "NO_CLASS_TODAY")
        student_ratio[sid] = (present_like / denom) if denom else 0.0

    return {"lessons": counts, "student_ratio": student_ratio}
