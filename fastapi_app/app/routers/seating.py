from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from app.db import get_session
from app.models.course import Course
from app.models.seating import SeatingPosition
from app.schemas.seating import SeatingPlanForm

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/course/{course_id}")
async def get_seating_plan(request: Request, course_id: int, session: Session = Depends(get_session)):
    course = session.get(Course, course_id)
    if not course:
        return {"error": "Course not found"}

    # Create seating positions if they don't exist
    for student in course.students:
        pos = session.exec(
            select(SeatingPosition).where(SeatingPosition.course_id == course_id, SeatingPosition.user_id == student.id)
        ).first()
        if not pos:
            pos = SeatingPosition(course_id=course_id, user_id=student.id, x=50, y=50)
            session.add(pos)
    session.commit()

    seating_plan = session.exec(select(SeatingPosition).where(SeatingPosition.course_id == course_id)).all()

    return templates.TemplateResponse(
        "seating/plan.html",
        {"request": request, "course": course, "seating_plan": seating_plan},
    )

@router.post("/course/{course_id}")
async def save_seating_plan(
    request: Request,
    course_id: int,
    form: SeatingPlanForm,
    session: Session = Depends(get_session),
):
    for pos_data in form.positions:
        pos = session.exec(
            select(SeatingPosition).where(SeatingPosition.course_id == course_id, SeatingPosition.user_id == pos_data.user_id)
        ).first()
        if pos:
            pos.x = pos_data.x
            pos.y = pos_data.y
            session.add(pos)

    session.commit()
    return {"message": "Seating plan saved successfully"}
