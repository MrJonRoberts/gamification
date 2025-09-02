from pydantic import BaseModel

class PointAdjustmentForm(BaseModel):
    user_id: int
    delta: int
    reason: str
