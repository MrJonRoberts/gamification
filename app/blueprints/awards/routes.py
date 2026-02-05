from __future__ import annotations
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from typing import List

from app.dependencies import get_current_user, get_db, require_user, AnonymousUser
from app.models import Award, AwardBadge, Badge, User, award_progress
from app.templating import render_template
from app.utils import flash

router = APIRouter(prefix="/awards", tags=["awards"])

@router.get("/", response_class=HTMLResponse, name="awards.list_awards")
def list_awards(
    request: Request,
    current_user: User | AnonymousUser = Depends(require_user),
    session: Session = Depends(get_db),
):
    items = session.query(Award).order_by(Award.name).all()
    return render_template("awards/list.html", {"request": request, "awards": items, "current_user": current_user})

@router.get("/create", response_class=HTMLResponse, name="awards.create_award")
def create_award_form(
    request: Request,
    current_user: User | AnonymousUser = Depends(require_user),
    session: Session = Depends(get_db),
):
    badges = session.query(Badge).order_by(Badge.name).all()
    return render_template("awards/form.html", {"request": request, "badges": badges, "current_user": current_user})

@router.post("/create", name="awards.create_award_post")
def create_award_action(
    request: Request,
    name: str = Form(...),
    description: str = Form(None),
    points: int = Form(0),
    badges: List[int] = Form([]),
    current_user: User | AnonymousUser = Depends(require_user),
    session: Session = Depends(get_db),
):
    a = Award(
        name=name.strip(),
        description=description.strip() if description else None,
        points=points,
        created_by_id=current_user.id
    )
    session.add(a)
    session.flush()

    for i, bid in enumerate(badges, start=1):
        session.add(AwardBadge(award_id=a.id, badge_id=bid, sequence=i))

    session.commit()
    flash(request, "Award created.", "success")
    return RedirectResponse("/awards/", status_code=303)

@router.get("/progress/{award_id}/{user_id}", response_class=HTMLResponse, name="awards.progress")
def progress(
    award_id: int,
    user_id: int,
    request: Request,
    current_user: User | AnonymousUser = Depends(require_user),
    session: Session = Depends(get_db),
):
    a = session.get(Award, award_id)
    u = session.get(User, user_id)
    if not a or not u:
        raise HTTPException(status_code=404, detail="Award or User not found")

    prog = award_progress(user_id=u.id, award_id=a.id)
    earned_dates = [v["earned_at"] for v in prog.values() if v["earned_at"]]
    completed = len(prog) > 0 and all(v["earned"] for v in prog.values())
    completed_at = max(earned_dates) if completed and earned_dates else None

    return render_template(
        "awards/progress.html",
        {
            "request": request,
            "award": a,
            "user": u,
            "progress": prog,
            "completed": completed,
            "completed_at": completed_at,
            "current_user": current_user,
        },
    )
