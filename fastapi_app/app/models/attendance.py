from typing import Optional, TYPE_CHECKING
from datetime import datetime
from enum import Enum
from sqlmodel import Field, SQLModel, Relationship
from sqlalchemy import UniqueConstraint

if TYPE_CHECKING:
    from .user import User
    from .schedule import Lesson


class AttendanceStatus(str, Enum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    LATE = "LATE"
    SCHOOL_APPROVED_ABSENT = "SCHOOL_APPROVED_ABSENT"
    NO_CLASS_TODAY = "NO_CLASS_TODAY"


class Attendance(SQLModel, table=True):
    __tablename__ = "attendance"
    __table_args__ = (
        UniqueConstraint("lesson_id", "student_id", name="uq_attendance_unique"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    lesson_id: int = Field(foreign_key="lessons.id", index=True)
    student_id: int = Field(foreign_key="users.id", index=True)
    marked_by_user_id: Optional[int] = Field(foreign_key="users.id")
    status: AttendanceStatus = Field(default=AttendanceStatus.PRESENT)
    marked_at: datetime = Field(default_factory=datetime.utcnow)
    comment: Optional[str] = None

    lesson: "Lesson" = Relationship(back_populates="attendance")
    student: "User" = Relationship(back_populates="attendances", sa_relationship_kwargs={"foreign_keys": "[Attendance.student_id]"})
    marked_by: Optional["User"] = Relationship(back_populates="marked_attendances", sa_relationship_kwargs={"foreign_keys": "[Attendance.marked_by_user_id]"})
