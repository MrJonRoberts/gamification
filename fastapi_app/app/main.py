from fastapi import FastAPI, Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from .config import settings
from .routers import auth, courses, badges, awards, points, attendance, schedule, seating, admin
from .models.user import User

app = FastAPI()

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY)

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(courses.router, prefix="/courses", tags=["courses"])
app.include_router(badges.router, prefix="/badges", tags=["badges"])
app.include_router(awards.router, prefix="/awards", tags=["awards"])
app.include_router(points.router, prefix="/points", tags=["points"])
app.include_router(attendance.router, prefix="/attendance", tags=["attendance"])
app.include_router(schedule.router, prefix="/schedule", tags=["schedule"])
app.include_router(seating.router, prefix="/seating", tags=["seating"])
app.include_router(admin.router, prefix="/admin", tags=["admin"])

@app.get("/")
async def root(request: Request, current_user: User = Depends(auth.get_current_user)):
    if not current_user:
        return RedirectResponse(url="/auth/login")
    return RedirectResponse(url="/courses")

@app.get("/profile")
async def profile(context: dict = Depends(auth.get_template_context)):
    # The user is already required by the dependency, but we can assert it for type checkers
    assert "current_user" in context
    return templates.TemplateResponse("profile.html", context)
