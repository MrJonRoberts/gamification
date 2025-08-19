from datetime import datetime, timedelta, date
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, abort
from flask_login import login_required, current_user
from app.extensions import db
from sqlalchemy import func
from app.services.attendance_service import ensure_attendance_rows, set_no_class_for_lesson
from app.models import Course, Lesson, User, Attendance, Enrollment, AttendanceStatus

# Map normalized statuses -> display metadata
STATUS_META = {
    "present": {"label": "Present", "icon": "fa-circle-check", "class": "att-present"},
    "absent": {"label": "Absent", "icon": "fa-circle-xmark", "class": "att-absent"},
    "late": {"label": "Late", "icon": "fa-clock", "class": "att-late"},
    "excused": {"label": "Excused", "icon": "fa-user-check", "class": "att-excused"},
    "unknown": {"label": "—", "icon": "fa-circle-minus", "class": "att-unknown"},
}
# UI-only placeholder for cells with no record yet
STATUS_UI_NOT_SET = {"label": "Not set", "icon": "fa-circle-minus", "class": "att-NOT_SET"}

def _norm_status(s: str) -> str:
    if not s:
        return "unknown"
    s = s.lower().strip()
    return s if s in STATUS_META else "unknown"

def _to_enum(code: str):
    """Normalize incoming status to one of the enum codes; return None if invalid."""
    if not code:
        return None
    s = code.strip().upper()
    # common synonyms
    if s == "EXCUSED":
        s = "SCHOOL_APPROVED_ABSENT"
    if s in STATUS_META:
        return s
    return None

def _parse_selected_date():
    qs = request.args.get("date", "").strip()
    if qs:
        try:
            return datetime.strptime(qs, "%Y-%m-%d").date()
        except ValueError:
            pass
    return date.today()


attendance_bp = Blueprint("attendance", __name__, url_prefix="/courses")

@attendance_bp.route("/<int:course_id>/lessons")
@login_required
def course_lessons(course_id):
    course = Course.query.get_or_404(course_id)
    lessons = (Lesson.query
               .filter_by(course_id=course.id)
               .order_by(Lesson.date.asc())
               .all())
    return render_template("attendance/course_lessons.html", course=course, lessons=lessons)

@attendance_bp.route("/<int:course_id>/lessons/<int:lesson_id>/roll", methods=["GET", "POST"])
@login_required
def roll(course_id, lesson_id):
    course = Course.query.get_or_404(course_id)
    lesson = Lesson.query.get_or_404(lesson_id)
    if lesson.course_id != course.id:
        flash("Lesson does not belong to this course.", "danger")
        return redirect(url_for("attendance.course_lessons", course_id=course.id))

    # Ensure rows exist for all enrolled students
    attendance_by_student = ensure_attendance_rows(course, lesson)

    if request.method == "POST":
        toggle = request.form.get("toggle_cancel")
        if toggle:
            set_no_class_for_lesson(lesson, on=(toggle == "on"))
            flash("Lesson updated.", "success")
            return redirect(url_for("attendance.roll", course_id=course.id, lesson_id=lesson.id))

        # Save statuses
        changed = 0
        for student in course.students:
            status_field = f"status_{student.id}"
            comment_field = f"comment_{student.id}"
            if status_field in request.form:
                a = attendance_by_student[student.id]
                new_status = request.form.get(status_field)
                new_comment = request.form.get(comment_field, "")[:255] or None
                if new_status in {AttendanceStatus.PRESENT, AttendanceStatus.ABSENT, AttendanceStatus.LATE, AttendanceStatus.SCHOOL_APPROVED_ABSENT, AttendanceStatus.NO_CLASS_TODAY}:
                    a.status = new_status
                    a.comment = new_comment
                    a.marked_by_user_id = getattr(current_user, "id", None)
                    changed += 1
        if changed:
            db.session.commit()
            flash(f"Saved roll for {changed} students.", "success")
        else:
            flash("No changes.", "info")
        return redirect(url_for("attendance.roll", course_id=course.id, lesson_id=lesson.id))

    # GET
    return render_template(
        "attendance/roll.html",
        course=course,
        lesson=lesson,
        attendance=attendance_by_student,
        enrollments=course.students,
    )

@login_required
@attendance_bp.get("/<int:course_id>/attendance")
def course_attendance(course_id):
    course = Course.query.get_or_404(course_id)
    selected_date = _parse_selected_date()

    # Lessons for course (optionally same-day filter if you have datetimes)
    lessons_q = Lesson.query.filter(Lesson.course_id == course.id)
    if hasattr(Lesson, "starts_at"):
        lessons_q = lessons_q.filter(func.date(Lesson.starts_at) == selected_date).order_by(Lesson.starts_at.asc())
    else:
        lessons_q = lessons_q.order_by(Lesson.id.asc())

    lessons = lessons_q.all()
    lesson_ids = [l.id for l in lessons]

    # Enrolled students
    students = (
        db.session.query(User)
        .join(Enrollment, Enrollment.c.user_id == User.id)
        .filter(Enrollment.c.course_id == course.id)
        .order_by(User.last_name.asc(), User.first_name.asc())
        .all()
    )
    student_ids = [u.id for u in students]

    # Attendance for those lessons+students (JOIN to Lesson to bind to course)
    att_rows = (
        Attendance.query
        .join(Lesson, Lesson.id == Attendance.lesson_id)
        .filter(Lesson.course_id == course.id)
        .filter(Attendance.lesson_id.in_(lesson_ids) if lesson_ids else True)
        .filter(Attendance.student_id.in_(student_ids) if student_ids else True)
        .all()
    )
    # map: (student_id, lesson_id) -> STATUS or None (no record)
    att_map = {(a.student_id, a.lesson_id): (a.status or None) for a in att_rows}

    # Per-lesson summary counts
    base = {"PRESENT": 0, "ABSENT": 0, "LATE": 0, "SCHOOL_APPROVED_ABSENT": 0, "NO_CLASS_TODAY": 0}
    counts = {lid: dict(base) for lid in lesson_ids}
    for (sid, lid), status in att_map.items():
        if status and lid in counts and status in counts[lid]:
            counts[lid][status] += 1

    # % present per student (count PRESENT and LATE as present; ignore NO_CLASS_TODAY; only count lessons with a record)
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
        course=course,
        students=students,
        lessons=lessons,
        att_map=att_map,
        status_meta=STATUS_META,
        status_ui_not_set=STATUS_UI_NOT_SET,
        counts=counts,
        student_present_ratio=student_present_ratio,
        selected_date=selected_date,
    )


@attendance_bp.route("/<int:course_id>/lessons/<int:lesson_id>/attendance", methods=["GET", "POST"])
@login_required
def mark_attendance(course_id, lesson_id):
    course = Course.query.get_or_404(course_id)
    lesson = Lesson.query.filter_by(id=lesson_id, course_id=course_id).first_or_404()
    # render your roll-marking UI here (or handle POST save)
    return render_template("attendance/mark.html", course=course, lesson=lesson)



@login_required
@attendance_bp.post("/<int:course_id>/attendance/api/set")
def api_set_attendance(course_id):
    data = request.get_json(silent=True) or {}
    lesson_id = data.get("lesson_id")
    student_id = data.get("user_id") or data.get("student_id")  # accept either
    status = _to_enum(data.get("status"))

    if not all([lesson_id, student_id, status]):
        return jsonify({"ok": False, "error": "Missing lesson_id, student_id, or invalid status"}), 400

    course = Course.query.get_or_404(course_id)
    lesson = Lesson.query.get_or_404(lesson_id)
    if lesson.course_id != course.id:
        abort(400, description="Lesson does not belong to course")

    # Ensure enrolled
    enrolled = db.session.query(Enrollment).filter(
        Enrollment.c.course_id == course.id,
        Enrollment.c.user_id == int(student_id)
    ).first()
    if not enrolled:
        return jsonify({"ok": False, "error": "Student not enrolled in course"}), 400

    rec = Attendance.query.filter_by(lesson_id=lesson_id, student_id=student_id).first()
    if not rec:
        rec = Attendance(lesson_id=lesson_id, student_id=student_id, status=status)
        db.session.add(rec)
    else:
        rec.status = status
    rec.marked_at = datetime.utcnow()
    rec.marked_by_user_id = getattr(current_user, "id", None)
    db.session.commit()
    return jsonify({"ok": True})



@login_required
@attendance_bp.post("/<int:course_id>/attendance/api/bulk_set")
def api_bulk_set_attendance(course_id):
    data = request.get_json(silent=True) or {}
    status = _to_enum(data.get("status"))
    if not status:
        return jsonify({"ok": False, "error": "Invalid status"}), 400

    lesson_id = data.get("lesson_id")
    lesson_ids = data.get("lesson_ids") or []
    targets = []
    if lesson_id:
        targets.append(int(lesson_id))
    if isinstance(lesson_ids, list):
        targets.extend([int(x) for x in lesson_ids if x is not None])

    course = Course.query.get_or_404(course_id)
    valid_lids = [lid for (lid,) in db.session.query(Lesson.id).filter(Lesson.course_id == course.id, Lesson.id.in_(targets))]
    if not valid_lids:
        return jsonify({"ok": False, "error": "No valid lessons for this course"}), 400

    student_ids = [uid for (uid,) in db.session.query(Enrollment.c.user_id).filter(Enrollment.c.course_id == course.id)]
    if not student_ids:
        return jsonify({"ok": True, "inserted": 0, "updated": 0})

    existing = {(a.student_id, a.lesson_id): a for a in Attendance.query.filter(
        Attendance.lesson_id.in_(valid_lids),
        Attendance.student_id.in_(student_ids)
    ).all()}

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
                db.session.add(Attendance(
                    lesson_id=lid, student_id=sid, status=status,
                    marked_at=now, marked_by_user_id=getattr(current_user, "id", None)
                ))
                inserted += 1
    db.session.commit()
    return jsonify({"ok": True, "inserted": inserted, "updated": updated})


@login_required
@attendance_bp.get("/<int:course_id>/attendance/api/summary")
def api_summary(course_id):
    course = Course.query.get_or_404(course_id)
    selected_date = _parse_selected_date()

    lessons_q = Lesson.query.filter(Lesson.course_id == course.id)
    if hasattr(Lesson, "starts_at"):
        lessons_q = lessons_q.filter(func.date(Lesson.starts_at) == selected_date)
    lessons = lessons_q.all()
    lesson_ids = [l.id for l in lessons]
    if not lesson_ids:
        return jsonify({"lessons": {}, "student_ratio": {}})

    # Group counts by status, via join to ensure course scoping
    raw = db.session.query(
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
            counts[lid][status] += int(cnt)

    # Student ratios
    student_ids = [uid for (uid,) in db.session.query(Enrollment.c.user_id).filter(Enrollment.c.course_id == course.id)]
    rows = Attendance.query.join(Lesson, Lesson.id == Attendance.lesson_id).filter(
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

    return jsonify({"lessons": counts, "student_ratio": student_ratio})

