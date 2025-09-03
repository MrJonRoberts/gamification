from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from app.db import get_session
from app.models.award import Award
from app.routers.auth import get_template_context

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/")
async def get_awards(context: dict = Depends(get_template_context), session: Session = Depends(get_session)):
    awards = session.exec(select(Award)).all()
    context["awards"] = awards
    return templates.TemplateResponse("awards/list.html", context)

@router.get("/new")
async def new_award_form(context: dict = Depends(get_template_context)):
    return templates.TemplateResponse("awards/form.html", context)

@router.post("/new")
async def create_award(
    request: Request,
    name: str = Form(...),
    description: str = Form(...),
    points: int = Form(...),
    session: Session = Depends(get_session),
):
    award = Award(name=name, description=description, points=points)
    session.add(award)
    session.commit()
    return RedirectResponse(url="/awards", status_code=303)
