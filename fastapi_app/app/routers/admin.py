from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, SQLModel
from app.db import get_session, engine
from app.routers.auth import get_template_context

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/")
async def admin_index(context: dict = Depends(get_template_context)):
    return templates.TemplateResponse("admin/index.html", context)

@router.post("/db/seed")
async def seed_database(request: Request, session: Session = Depends(get_session)):
    # Placeholder for seeding logic
    # In a real app, you would call a seeding script here.
    return templates.TemplateResponse(
        "partials/htmx_toast.html",
        {"request": request, "message": "Database seeding not implemented yet."},
    )

@router.post("/db/clear")
async def clear_database(request: Request, session: Session = Depends(get_session)):
    # This is a destructive operation and should be used with caution.
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    return templates.TemplateResponse(
        "partials/htmx_toast.html",
        {"request": request, "message": "Database cleared and re-created."},
    )
