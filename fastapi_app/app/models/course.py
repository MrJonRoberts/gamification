from typing import List, Optional, TYPE_CHECKING
from datetime import datetime
from sqlmodel import Field, SQLModel, Relationship
from sqlalchemy import UniqueConstraint, Index
from .user import User
from .link_models import Enrollment

if TYPE_CHECKING:
    from .schedule import WeeklyPattern, Lesson
    from .seating import SeatingPosition

class Course(SQLModel, table=True):
    __tablename__ = "courses"
    __table_args__ = (
        UniqueConstraint("name", "semester", "year", name="uq_course_term"),
        Index("ix_course_term", "year", "semester"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    semester: str  # "S1" | "S2" | "FULL"
    year: int
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    students: List[User] = Relationship(back_populates="courses", link_model=Enrollment)
    schedules: List["WeeklyPattern"] = Relationship(back_populates="course")
    lessons: List["Lesson"] = Relationship(back_populates="course")
    seating_positions: List["SeatingPosition"] = Relationship(back_populates="course")
