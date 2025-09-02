from typing import List, Optional, TYPE_CHECKING
from datetime import date, time
from enum import Enum
from sqlmodel import Field, SQLModel, Relationship
from sqlalchemy import UniqueConstraint, CheckConstraint

if TYPE_CHECKING:
    from .course import Course
    from .attendance import Attendance


class LessonStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    NO_CLASS_TODAY = "NO_CLASS_TODAY"


class AcademicYear(SQLModel, table=True):
    __tablename__ = "academic_years"

    id: Optional[int] = Field(default=None, primary_key=True)
    year: int = Field(unique=True)
    source: Optional[str] = None
    last_updated: Optional[date] = None

    terms: List["Term"] = Relationship(back_populates="academic_year")


class Term(SQLModel, table=True):
    __tablename__ = "terms"
    __table_args__ = (
        UniqueConstraint("academic_year_id", "number", name="uq_year_termnum"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    academic_year_id: int = Field(foreign_key="academic_years.id")
    number: int  # 1..4
    name: str  # "Term 1"
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    weeks: Optional[int] = None
    raw: Optional[str] = None

    academic_year: "AcademicYear" = Relationship(back_populates="terms")


class WeeklyPattern(SQLModel, table=True):
    __tablename__ = "weekly_patterns"
    __table_args__ = (
        UniqueConstraint("course_id", "day_of_week", name="uq_course_day"),
        CheckConstraint("day_of_week BETWEEN 0 AND 6", name="ck_valid_dow"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    course_id: int = Field(foreign_key="courses.id")
    day_of_week: int  # Monday=0..Sunday=6
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    room: Optional[str] = None
    is_active: bool = True

    course: "Course" = Relationship(back_populates="schedules")


class Lesson(SQLModel, table=True):
    __tablename__ = "lessons"
    __table_args__ = (
        UniqueConstraint("course_id", "date", name="uq_course_lesson_date"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    course_id: int = Field(foreign_key="courses.id")
    term_id: int = Field(foreign_key="terms.id")
    date: date
    week_of_term: int
    status: LessonStatus = Field(default=LessonStatus.SCHEDULED)
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    notes: Optional[str] = None

    term: "Term" = Relationship()
    course: "Course" = Relationship(back_populates="lessons")
    attendance: List["Attendance"] = Relationship(back_populates="lesson")
