# seeds/example_courses.py
from datetime import time
from app.extensions import db
from app.models.schedule import Course, WeeklyPattern, SchoolYear, SemesterEnum
from app.models import Student, Enrollment  # reusing your models
from services.schedule_service import generate_lessons_for_course

def seed_example_courses():
    year_2025 = SchoolYear.query.filter_by(year=2025).first()  # ensure year exists (see term seed below)
    if not year_2025:
        raise RuntimeError("Create Year 2025 first.")

    # Y7 Digital Tech: Semester 1; Mon/Tue
    c1 = Course(name="Y7 Digital Tech", code="Y7DT", school_year_id=year_2025.id, semester=SemesterEnum.S1)
    db.session.add(c1); db.session.flush()
    db.session.add_all([
        WeeklyPattern(course_id=c1.id, day_of_week=0),  # Monday
        WeeklyPattern(course_id=c1.id, day_of_week=1),  # Tuesday
    ])

    # Y9 Game Design: FULL year with Mon/Tue/Thu/Fri (or make it S2 if you prefer)
    c2 = Course(name="Y9 Game Design", code="Y9GD", school_year_id=year_2025.id, semester=SemesterEnum.FULL)
    db.session.add(c2); db.session.flush()
    db.session.add_all([
        WeeklyPattern(course_id=c2.id, day_of_week=0),  # Mon
        WeeklyPattern(course_id=c2.id, day_of_week=1),  # Tue
        WeeklyPattern(course_id=c2.id, day_of_week=3),  # Thu
        WeeklyPattern(course_id=c2.id, day_of_week=4),  # Fri
    ])

    db.session.commit()
    generate_lessons_for_course(c1.id)
    generate_lessons_for_course(c2.id)
