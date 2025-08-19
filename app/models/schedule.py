from datetime import time
from app.extensions import db
from sqlalchemy.orm import synonym

# Keep Course.semester as string: "S1", "S2", "FULL"

# class SchoolYear(db.Model):
#     __tablename__ = "school_years"
#     id = db.Column(db.Integer, primary_key=True)
#     year = db.Column(db.Integer, unique=True, nullable=False)
#     start_date = db.Column(db.Date, nullable=False)
#     end_date = db.Column(db.Date, nullable=False)
#     is_active = db.Column(db.Boolean, default=True)

class AcademicYear(db.Model):
    __tablename__ = "academic_years"
    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, nullable=False, unique=True)
    source = db.Column(db.String(255))
    last_updated = db.Column(db.Date, nullable=True)
    terms = db.relationship("Term", backref="academic_year", cascade="all, delete-orphan", order_by="Term.number")

class Term(db.Model):
    __tablename__ = "terms"
    id = db.Column(db.Integer, primary_key=True)
    academic_year_id = db.Column(db.Integer, db.ForeignKey("academic_years.id"), nullable=False)
    number = db.Column(db.Integer, nullable=False)      # 1..4
    name = db.Column(db.String(50), nullable=False)     # "Term 1"
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)
    weeks = db.Column(db.Integer, nullable=True)
    raw = db.Column(db.Text, nullable=True)
    __table_args__ = (db.UniqueConstraint("academic_year_id", "number", name="uq_year_termnum"),)



class LessonStatus(db.Enum):
    SCHEDULED = "SCHEDULED"
    NO_CLASS_TODAY = "NO_CLASS_TODAY"

# Note: If you prefer Python Enum: use `from enum import Enum` and `db.Enum(EnumClass)` instead.

class WeeklyPattern(db.Model):
    __tablename__ = "weekly_patterns"
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=False)
    day_of_week = db.Column(db.Integer, nullable=False)  # Monday=0..Sunday=6
    start_time = db.Column(db.Time)  # optional
    end_time = db.Column(db.Time)
    room = db.Column(db.String(64))
    is_active = db.Column(db.Boolean, default=True)

    course = db.relationship("Course", backref=db.backref("schedules", cascade="all, delete-orphan"))

    __table_args__ = (
        db.UniqueConstraint("course_id", "day_of_week", name="uq_course_day"),
        db.CheckConstraint("day_of_week BETWEEN 0 AND 6", name="ck_valid_dow"),
    )

class Lesson(db.Model):
    __tablename__ = "lessons"
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=False)
    term_id = db.Column(db.Integer, db.ForeignKey("terms.id"), nullable=False)
    date = db.Column(db.Date, nullable=False)
    week_of_term = db.Column(db.Integer, nullable=False)
    status = db.Column(db.Enum("SCHEDULED", "NO_CLASS_TODAY", name="lesson_status"), nullable=False, default="SCHEDULED")
    start_time = db.Column(db.Time)
    end_time = db.Column(db.Time)
    notes = db.Column(db.Text)

    term = db.relationship("Term")
    course = db.relationship("Course", backref=db.backref("lessons", cascade="all, delete-orphan"))

    # Alias so `Lesson.starts_at` works everywhere
    starts_at = synonym("start_time")

    __table_args__ = (db.UniqueConstraint("course_id", "date", name="uq_course_lesson_date"),)


#
# # --- Optional model for year/terms (simple, single-table) ---
# class AcademicYear(db.Model):
#     __tablename__ = "academic_years"
#     id = db.Column(db.Integer, primary_key=True)
#     year = db.Column(db.Integer, unique=True, nullable=False)
#
#     term1_start = db.Column(db.Date, nullable=True)
#     term1_end   = db.Column(db.Date, nullable=True)
#     term2_start = db.Column(db.Date, nullable=True)
#     term2_end   = db.Column(db.Date, nullable=True)
#     term3_start = db.Column(db.Date, nullable=True)
#     term3_end   = db.Column(db.Date, nullable=True)
#     term4_start = db.Column(db.Date, nullable=True)
#     term4_end   = db.Column(db.Date, nullable=True)