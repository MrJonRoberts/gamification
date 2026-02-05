from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db, require_user, AnonymousUser
from app.models import PointLedger, User
from app.templating import render_template
from app.extensions import db

router = APIRouter(tags=["main"])

@router.get("/", response_class=HTMLResponse, name="main.index")
def index(
    request: Request,
    current_user: User | AnonymousUser = Depends(require_user),
    session: Session = Depends(get_db),
):
    """
    Renders the homepage with the student leaderboard.
    """
    rows = session.execute(
        db.select(
            User.id,
            User.first_name,
            User.last_name,
            func.coalesce(func.sum(PointLedger.delta), 0).label("points"),
        )
        .outerjoin(PointLedger, PointLedger.user_id == User.id)
        .where(User.role == "student")
        .group_by(User.id)
        .order_by(func.sum(PointLedger.delta).desc())
        .limit(20)
    ).all()
    return render_template(
        "index.html",
        {
            "request": request,
            "leaderboard": rows,
            "current_user": current_user,
        },
    )

@router.get("/timer", response_class=HTMLResponse, name="main.timer")
def timer(request: Request, current_user: User | AnonymousUser = Depends(require_user)):
    """
    Renders a simple countdown timer page.
    """
    return render_template(
        "timer.html",
        {
            "request": request,
            "current_user": current_user,
        },
    )
