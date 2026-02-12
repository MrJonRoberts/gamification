from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import inspect, text

from app.config import settings
from app.extensions import db
from app.routers.auth.routes import router as auth_router
from app.routers.main.routes import router as main_router
from app.routers.students.routes import router as students_router
from app.routers.courses.routes import router as courses_router
from app.routers.badges.routes import router as badges_router
from app.routers.awards.routes import router as awards_router
from app.routers.points.routes import router as points_router
from app.routers.admin.routes import router as admin_router
from app.routers.behaviours.routes import router as behaviours_router
from app.routers.seating.routes import router as seating_router
from app.routers.attendance.routes import router as attendance_router
from app.routers.schedule.routes import router as schedule_router




def _ensure_course_is_active_column() -> None:
    """Backfill schema for instances created before Course.is_active existed."""
    inspector = inspect(db.engine)
    if not inspector.has_table("courses"):
        return

    columns = {column["name"] for column in inspector.get_columns("courses")}
    if "is_active" in columns:
        return

    with db.engine.begin() as conn:
        conn.execute(text("ALTER TABLE courses ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1"))

def create_app() -> FastAPI:
    """
    Application factory to create and configure the FastAPI instance.
    Sets up middleware, static files, and includes all routers.
    """
    app = FastAPI(title=settings.APP_NAME, version=settings.APP_VERSION)

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.SECRET_KEY,
        same_site=settings.SESSION_COOKIE_SAMESITE,
        https_only=settings.SESSION_COOKIE_SECURE,
    )

    app.mount("/static", StaticFiles(directory="app/static"), name="static")

    _ensure_course_is_active_column()

    # Include routers
    app.include_router(main_router)
    app.include_router(auth_router)
    app.include_router(students_router)
    app.include_router(courses_router)
    app.include_router(badges_router)
    app.include_router(awards_router)
    app.include_router(points_router)
    app.include_router(admin_router)
    app.include_router(behaviours_router)
    app.include_router(seating_router)
    app.include_router(attendance_router)
    app.include_router(schedule_router)

    return app


app = create_app()
