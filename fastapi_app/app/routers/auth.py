from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from app.models.user import User
from app.schemas.auth import RegisterForm
from app.db import get_session

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

# --- Dependencies ---

def get_current_user(request: Request, session: Session = Depends(get_session)) -> Optional[User]:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    user = session.get(User, user_id)
    return user

def require_login(current_user: Optional[User] = Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return current_user

async def get_template_context(request: Request, current_user: Optional[User] = Depends(get_current_user)):
    return {"request": request, "current_user": current_user}

# --- Routes ---

@router.get("/login")
async def login_form(context: dict = Depends(get_template_context)):
    return templates.TemplateResponse("auth/login.html", context)

@router.post("/login")
async def login(request: Request, email: str = Form(...), password: str = Form(...), session: Session = Depends(get_session)):
    user = session.exec(select(User).where(User.email == email)).first()
    if not user or not user.check_password(password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    request.session["user_id"] = user.id
    # Redirect to profile page after login
    response = Response(status_code=status.HTTP_303_SEE_OTHER)
    response.headers["Location"] = "/profile"
    return response

@router.get("/register")
async def register_form(context: dict = Depends(get_template_context)):
    return templates.TemplateResponse("auth/register.html", context)

@router.post("/register")
async def register(request: Request, form_data: RegisterForm = Depends(RegisterForm.as_form), session: Session = Depends(get_session)):
    # This is a simplified registration. In a real app, you'd have more validation.
    user = User(
        first_name=form_data.first_name,
        last_name=form_data.last_name,
        email=form_data.email,
    )
    user.set_password(form_data.password)
    session.add(user)
    session.commit()
    session.refresh(user)

    request.session["user_id"] = user.id
    # Redirect to profile page after registration
    response = Response(status_code=status.HTTP_303_SEE_OTHER)
    response.headers["Location"] = "/profile"
    return response

@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    # Redirect to home page after logout
    response = Response(status_code=status.HTTP_303_SEE_OTHER)
    response.headers["Location"] = "/"
    return response
