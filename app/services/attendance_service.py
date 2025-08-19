
from typing import Dict
from app.extensions import db
from app.models import Attendance, AttendanceStatus, Lesson, Course

def ensure_attendance_rows(course: Course, lesson: Lesson) -> Dict[int, Attendance]:
    """Ensure every enrolled student in `course` has an Attendance row for `lesson`.
    Returns dict keyed by student_id."""
    attendance = {a.student_id: a for a in lesson.attendance}
    changed = False
    # course.students is dynamic; iterate to fetch all
    for student in course.students:
        if student.id not in attendance:
            a = Attendance(lesson_id=lesson.id, student_id=student.id, status=AttendanceStatus.PRESENT)
            db.session.add(a)
            attendance[student.id] = a
            changed = True
    if changed:
        db.session.commit()
    return attendance

def set_no_class_for_lesson(lesson: Lesson, on: bool):
    if on:
        lesson.status = "NO_CLASS_TODAY"
        for a in lesson.attendance:
            a.status = AttendanceStatus.NO_CLASS_TODAY
    else:
        lesson.status = "SCHEDULED"
    db.session.commit()
