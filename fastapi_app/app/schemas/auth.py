from pydantic import BaseModel

class LoginForm(BaseModel):
    email: str
    password: str

from fastapi import Form

class RegisterForm(BaseModel):
    first_name: str
    last_name: str
    email: str
    password: str

    @classmethod
    def as_form(
        cls,
        first_name: str = Form(...),
        last_name: str = Form(...),
        email: str = Form(...),
        password: str = Form(...),
    ):
        return cls(
            first_name=first_name,
            last_name=last_name,
            email=email,
            password=password,
        )
