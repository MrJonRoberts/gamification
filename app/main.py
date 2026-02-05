from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.blueprints.auth.routes import router as auth_router
from app.blueprints.main.routes import router as main_router
from app.blueprints.students.routes import router as students_router
from app.blueprints.courses.routes import router as courses_router
from app.blueprints.badges.routes import router as badges_router
from app.blueprints.awards.routes import router as awards_router
from app.blueprints.points.routes import router as points_router
from app.blueprints.admin.routes import router as admin_router
from app.blueprints.behaviours.routes import router as behaviours_router
from app.blueprints.seating.routes import router as seating_router
from app.blueprints.attendance.routes import router as attendance_router
from app.blueprints.schedule.routes import router as schedule_router


def create_app() -> FastAPI:
    app = FastAPI(title=settings.APP_NAME, version=settings.APP_VERSION)

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.SECRET_KEY,
        same_site=settings.SESSION_COOKIE_SAMESITE,
        https_only=settings.SESSION_COOKIE_SECURE,
    )

    app.mount("/static", StaticFiles(directory="app/static"), name="static")

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
