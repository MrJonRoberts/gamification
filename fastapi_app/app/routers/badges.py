from typing import List
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from app.db import get_session
from app.models.badge import Badge, BadgeGrant
from app.models.user import User
from app.routers.auth import get_template_context

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/")
async def get_badges(context: dict = Depends(get_template_context), session: Session = Depends(get_session)):
    badges = session.exec(select(Badge)).all()
    context["badges"] = badges
    return templates.TemplateResponse("badges/list.html", context)

@router.get("/new")
async def new_badge_form(context: dict = Depends(get_template_context)):
    return templates.TemplateResponse("badges/form.html", context)

@router.post("/new")
async def create_badge(
    request: Request,
    name: str = Form(...),
    description: str = Form(...),
    points: int = Form(...),
    session: Session = Depends(get_session),
):
    badge = Badge(name=name, description=description, points=points)
    session.add(badge)
    session.commit()
    return RedirectResponse(url="/badges", status_code=303)

@router.get("/{badge_id}/grant")
async def grant_badge_form(badge_id: int, context: dict = Depends(get_template_context), session: Session = Depends(get_session)):
    badge = session.get(Badge, badge_id)
    if not badge:
        return {"error": "Badge not found"}

    all_students = session.exec(select(User).where(User.role == "student")).all()
    context["badge"] = badge
    context["all_students"] = all_students
    return templates.TemplateResponse("badges/grant.html", context)

@router.post("/{badge_id}/grant")
async def grant_badge(
    request: Request,
    badge_id: int,
    student_ids: List[int] = Form(...),
    session: Session = Depends(get_session),
):
    badge = session.get(Badge, badge_id)
    if not badge:
        return {"error": "Badge not found"}

    for student_id in student_ids:
        # In a real app, you'd check if the grant already exists
        badge_grant = BadgeGrant(badge_id=badge_id, user_id=student_id)
        session.add(badge_grant)

    session.commit()
    return RedirectResponse(url="/badges", status_code=303)
