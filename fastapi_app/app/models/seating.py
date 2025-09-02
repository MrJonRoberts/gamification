from typing import Optional, TYPE_CHECKING
from datetime import datetime
from sqlmodel import Field, SQLModel, Relationship
from sqlalchemy import UniqueConstraint

if TYPE_CHECKING:
    from .user import User
    from .course import Course


class SeatingPosition(SQLModel, table=True):
    __tablename__ = "seating_positions"
    __table_args__ = (
        UniqueConstraint("course_id", "user_id", name="uq_seating_course_user"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    course_id: int = Field(foreign_key="courses.id", index=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    x: float = 0.0
    y: float = 0.0
    locked: bool = False
    updated_at: datetime = Field(default_factory=datetime.utcnow, sa_column_kwargs={"onupdate": datetime.utcnow})

    course: "Course" = Relationship(back_populates="seating_positions")
    user: "User" = Relationship(back_populates="seating_positions")
