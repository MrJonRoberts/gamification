from typing import List
from pydantic import BaseModel

class SeatingPositionData(BaseModel):
    user_id: int
    x: float
    y: float

class SeatingPlanForm(BaseModel):
    positions: List[SeatingPositionData]
