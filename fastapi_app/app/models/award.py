from typing import List, Optional
from datetime import datetime
from sqlmodel import Field, SQLModel, Relationship
from sqlalchemy import UniqueConstraint
from .user import User
from .badge import Badge
from .link_models import AwardBadge


class Award(SQLModel, table=True):
    __tablename__ = "awards"
    __table_args__ = (
        UniqueConstraint("name", name="uq_award_name"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True)
    description: Optional[str] = None
    icon: Optional[str] = None
    points: int = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    created_by_id: Optional[int] = Field(foreign_key="users.id")

    created_by: Optional["User"] = Relationship()
    badges: List["Badge"] = Relationship(back_populates="awards", link_model=AwardBadge)
