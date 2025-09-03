from fastapi import APIRouter, Depends, Form, Request
from fastapi.templating import Jinja2Templates
from sqlmodel import Session
from app.db import get_session
from app.models.user import User
from app.models.course import Course
from app.routers.auth import get_template_context

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/new")
async def new_student_form(request: Request, course_id: int):
    return templates.TemplateResponse("students/_form.html", {"request": request, "course_id": course_id})

@router.post("/")
async def create_student(
    request: Request,
    course_id: int,
    first_name: str = Form(...),
    last_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    session: Session = Depends(get_session),
):
    # Create the new student
    new_student = User(
        first_name=first_name,
        last_name=last_name,
        email=email,
        role="student",
    )
    new_student.set_password(password)
    session.add(new_student)
    session.commit()
    session.refresh(new_student)

    # Enroll the new student in the course
    course = session.get(Course, course_id)
    if course:
        course.students.append(new_student)
        session.add(course)
        session.commit()
        session.refresh(course)

    # Return the updated list of enrolled students
    return templates.TemplateResponse(
        "courses/_enrolled_students_partial.html",
        {"request": request, "course": course},
    )
