from pydantic import BaseModel

class BadgeForm(BaseModel):
    name: str
    description: str
    points: int
