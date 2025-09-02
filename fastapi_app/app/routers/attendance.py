from datetime import date
from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from app.db import get_session
from app.models.attendance import Attendance, AttendanceStatus
from app.models.schedule import Lesson
from app.models.user import User
from app.utils.calendar import generate_calendar_data
from app.routers.auth import require_login

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/")
async def get_calendar(request: Request, current_user: User = Depends(require_login), session: Session = Depends(get_session)):
    # For now, just show the current month. A real app would have month navigation.
    today = date.today()
    calendar_data = generate_calendar_data(today.year, today.month)

    # In a real app, you'd fetch lessons for the logged-in user (instructor)
    # For now, we'll just fetch all lessons for simplicity.
    lessons = session.exec(select(Lesson)).all()
    lessons_by_date = {lesson.date: lesson for lesson in lessons}

    for week in calendar_data:
        for day in week:
            if day["date"] in lessons_by_date:
                day["lesson"] = lessons_by_date[day["date"]]

    return templates.TemplateResponse(
        "attendance/calendar.html",
        {"request": request, "calendar_data": calendar_data},
    )

@router.get("/lesson/{lesson_id}")
async def get_attendance_sheet(request: Request, lesson_id: int, session: Session = Depends(get_session)):
    lesson = session.get(Lesson, lesson_id)
    if not lesson:
        return {"error": "Lesson not found"}

    # Create attendance records if they don't exist for this lesson
    enrolled_students = lesson.course.students
    for student in enrolled_students:
        record = session.exec(
            select(Attendance).where(Attendance.lesson_id == lesson_id, Attendance.student_id == student.id)
        ).first()
        if not record:
            record = Attendance(lesson_id=lesson_id, student_id=student.id, status=AttendanceStatus.PRESENT)
            session.add(record)
    session.commit()

    attendance_records = session.exec(select(Attendance).where(Attendance.lesson_id == lesson_id)).all()

    return templates.TemplateResponse(
        "attendance/_sheet.html",
        {"request": request, "lesson": lesson, "attendance_records": attendance_records},
    )

@router.post("/lesson/{lesson_id}/mark-all/{status}")
async def mark_all(request: Request, lesson_id: int, status: AttendanceStatus, session: Session = Depends(get_session)):
    lesson = session.get(Lesson, lesson_id)
    if not lesson:
        return {"error": "Lesson not found"}

    records = session.exec(select(Attendance).where(Attendance.lesson_id == lesson_id)).all()
    for record in records:
        record.status = status
        session.add(record)
    session.commit()

    attendance_records = session.exec(select(Attendance).where(Attendance.lesson_id == lesson_id)).all()
    return templates.TemplateResponse(
        "attendance/_sheet.html",
        {"request": request, "lesson": lesson, "attendance_records": attendance_records},
    )

@router.post("/record/{record_id}/next-status")
async def next_status(request: Request, record_id: int, session: Session = Depends(get_session)):
    record = session.get(Attendance, record_id)
    if not record:
        return {"error": "Attendance record not found"}

    statuses = [s.value for s in AttendanceStatus]
    current_index = statuses.index(record.status)
    next_index = (current_index + 1) % len(statuses)
    record.status = statuses[next_index]

    session.add(record)
    session.commit()
    session.refresh(record)

    return templates.TemplateResponse(
        "attendance/_student_row.html",
        {"request": request, "record": record},
    )
