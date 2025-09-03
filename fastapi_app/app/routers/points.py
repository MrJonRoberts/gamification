from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from app.db import get_session
from app.models.point_ledger import PointLedger
from app.models.user import User
from app.routers.auth import get_template_context

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/adjust")
async def adjust_points_form(context: dict = Depends(get_template_context), session: Session = Depends(get_session)):
    users = session.exec(select(User)).all()
    context["users"] = users
    return templates.TemplateResponse("points/adjust.html", context)

@router.post("/adjust")
async def adjust_points(
    request: Request,
    user_id: int = Form(...),
    delta: int = Form(...),
    reason: str = Form(...),
    session: Session = Depends(get_session),
):
    point_entry = PointLedger(
        user_id=user_id,
        delta=delta,
        reason=reason,
        source="manual",
    )
    session.add(point_entry)
    session.commit()
    # In a real app, you might redirect to the user's profile or a points history page
    return RedirectResponse(url="/", status_code=303)
