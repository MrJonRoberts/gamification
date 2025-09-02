from pydantic import BaseModel

class AwardForm(BaseModel):
    name: str
    description: str
    points: int
