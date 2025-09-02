from datetime import date
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from app.db import get_session
from app.models.schedule import AcademicYear, Term

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/")
async def schedule_index(request: Request, session: Session = Depends(get_session)):
    # In a real app, you'd list the existing academic years
    return templates.TemplateResponse("schedule/index.html", {"request": request})

@router.get("/year/new")
async def new_year_form(request: Request):
    return templates.TemplateResponse("schedule/year_setup.html", {"request": request})

@router.post("/year/new")
async def create_academic_year(
    request: Request,
    year: int = Form(...),
    term1_start_date: date = Form(None),
    term1_end_date: date = Form(None),
    term2_start_date: date = Form(None),
    term2_end_date: date = Form(None),
    term3_start_date: date = Form(None),
    term3_end_date: date = Form(None),
    term4_start_date: date = Form(None),
    term4_end_date: date = Form(None),
    session: Session = Depends(get_session),
):
    academic_year = AcademicYear(year=year)
    session.add(academic_year)
    session.commit()
    session.refresh(academic_year)

    terms_data = [
        {"number": 1, "name": "Term 1", "start_date": term1_start_date, "end_date": term1_end_date},
        {"number": 2, "name": "Term 2", "start_date": term2_start_date, "end_date": term2_end_date},
        {"number": 3, "name": "Term 3", "start_date": term3_start_date, "end_date": term3_end_date},
        {"number": 4, "name": "Term 4", "start_date": term4_start_date, "end_date": term4_end_date},
    ]

    for term_data in terms_data:
        term = Term(academic_year_id=academic_year.id, **term_data)
        session.add(term)

    session.commit()
    return RedirectResponse(url="/schedule", status_code=303)
