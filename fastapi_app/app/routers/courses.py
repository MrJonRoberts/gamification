import csv
import io
from typing import List
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from app.db import get_session
from app.models.course import Course
from app.models.user import User
from app.schemas.course import CourseForm
from app.routers.auth import get_template_context
from fastapi.responses import RedirectResponse

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/")
async def get_courses(context: dict = Depends(get_template_context), session: Session = Depends(get_session)):
    courses = session.exec(select(Course)).all()
    context["courses"] = courses
    return templates.TemplateResponse("courses/list.html", context)

@router.get("/new")
async def new_course_form(context: dict = Depends(get_template_context)):
    return templates.TemplateResponse("courses/_form.html", context)

@router.post("/")
async def create_course(
    request: Request,
    name: str = Form(...),
    semester: str = Form(...),
    year: int = Form(...),
    session: Session = Depends(get_session),
):
    course = Course(name=name, semester=semester, year=year)
    session.add(course)
    session.commit()

    courses = session.exec(select(Course)).all()
    return templates.TemplateResponse("courses/_list_partial.html", {"request": request, "courses": courses})

@router.post("/upload-csv")
async def upload_courses_csv(request: Request, file: UploadFile = File(...), session: Session = Depends(get_session)):
    try:
        contents = await file.read()
        buffer = io.StringIO(contents.decode("utf-8"))
        reader = csv.DictReader(buffer)
        for row in reader:
            course = Course(
                name=row["name"],
                semester=row["semester"],
                year=int(row["year"]),
            )
            session.add(course)
        session.commit()
    except Exception as e:
        # In a real app, you'd handle errors more gracefully
        print(f"Error processing CSV: {e}")

    courses = session.exec(select(Course)).all()
    return templates.TemplateResponse("courses/_list_partial.html", {"request": request, "courses": courses})

@router.get("/{course_id}")
async def get_course_details(course_id: int, context: dict = Depends(get_template_context), session: Session = Depends(get_session)):
    course = session.get(Course, course_id)
    if not course:
        # In a real app, you'd have a proper 404 page
        return {"error": "Course not found"}
    context["course"] = course
    return templates.TemplateResponse("courses/detail.html", context)

@router.get("/{course_id}/enroll")
async def enroll_form(course_id: int, context: dict = Depends(get_template_context), session: Session = Depends(get_session)):
    course = session.get(Course, course_id)
    if not course:
        return {"error": "Course not found"}

    enrolled_student_ids = {student.id for student in course.students}
    all_students = session.exec(select(User).where(User.role == "student")).all()
    available_students = [student for student in all_students if student.id not in enrolled_student_ids]

    context["course"] = course
    context["all_students"] = available_students
    return templates.TemplateResponse("courses/enroll.html", context)

@router.post("/{course_id}/enroll")
async def enroll_students(request: Request, course_id: int, student_ids: List[int] = Form(...), session: Session = Depends(get_session)):
    course = session.get(Course, course_id)
    if not course:
        return {"error": "Course not found"}

    for student_id in student_ids:
        student = session.get(User, student_id)
        if student:
            course.students.append(student)

    session.add(course)
    session.commit()
    session.refresh(course)

    return templates.TemplateResponse(
        "courses/_enrolled_students_partial.html",
        {"request": request, "course": course},
    )

@router.get("/{course_id}/students/upload")
async def upload_students_form(course_id: int, context: dict = Depends(get_template_context), session: Session = Depends(get_session)):
    course = session.get(Course, course_id)
    if not course:
        return {"error": "Course not found"}
    context["course"] = course
    return templates.TemplateResponse("students/upload.html", context)

@router.post("/{course_id}/students/upload-csv")
async def upload_students_csv(
    course_id: int,
    file: UploadFile = File(...),
    session: Session = Depends(get_session)
):
    course = session.get(Course, course_id)
    if not course:
        return {"error": "Course not found"}

    try:
        contents = await file.read()
        buffer = io.StringIO(contents.decode("utf-8"))
        reader = csv.DictReader(buffer)
        for row in reader:
            student = User(
                first_name=row["first_name"],
                last_name=row["last_name"],
                email=row["email"],
                role="student",
            )
            student.set_password(row["password"])
            session.add(student)
            course.students.append(student)

        session.commit()
    except Exception as e:
        # In a real app, you'd handle errors more gracefully
        print(f"Error processing student CSV: {e}")

    return RedirectResponse(url=f"/courses/{course_id}/enroll", status_code=303)
