from datetime import date, datetime, time as dtime, timedelta
from app.extensions import db
from app.models import AcademicYear, Term, Course, WeeklyPattern, Lesson, LessonStatus


def _terms_map(year_obj):
    return {t.number: t for t in sorted(year_obj.terms, key=lambda x: x.number)}

def semester_date_span(year_obj, semester: str):
    terms = _terms_map(year_obj)
    if semester == "S1":
        return terms[1].start_date, terms[2].end_date
    if semester == "S2":
        return terms[3].start_date, terms[4].end_date
    # FULL year
    return terms[1].start_date, terms[4].end_date

def which_term_for_date(year_obj, d):
    for t in year_obj.terms:
        if t.start_date <= d <= t.end_date:
            return t
    return None

def week_of_term(term, d):
    return ((d - term.start_date).days // 7) + 1

def generate_lessons_for_course(course_id: int) -> int:
    course = db.session.get(Course, course_id)
    if not course:
        raise ValueError(f"Course {course_id} not found")
    year_obj = AcademicYear.query.filter_by(year=course.year).first()
    if not year_obj:
        raise ValueError(f"Academic year {course.year} not configured")

    start, end = semester_date_span(year_obj, course.semester)
    active_days = {wp.day_of_week: wp for wp in course.schedules if wp.is_active}
    if not active_days:
        return 0

    created = 0
    d = start
    while d <= end:
        if d.weekday() in active_days:
            term = which_term_for_date(year_obj, d)
            if term:
                exists = Lesson.query.filter_by(course_id=course.id, date=d).first()
                if not exists:
                    wp = active_days[d.weekday()]
                    lesson = Lesson(
                        course_id=course.id,
                        term_id=term.id,
                        date=d,
                        week_of_term=week_of_term(term, d),
                        status=LessonStatus.SCHEDULED,
                        start_time=wp.start_time,
                        end_time=wp.end_time,
                    )
                    db.session.add(lesson)
                    created += 1
        d += timedelta(days=1)
    db.session.commit()
    return created

def get_terms_for(year: int, term_numbers: list[int]) -> list[Term]:
    return (Term.query.join(AcademicYear, Term.academic_year_id == AcademicYear.id)
            .filter(AcademicYear.year == year, Term.number.in_(term_numbers))
            .order_by(Term.number.asc())
            .all())

def ensure_year_has_terms(year: int, needed_terms: list[int]) -> bool:
    from app.models import AcademicYear, Term, Course, WeeklyPattern, Lesson, LessonStatus
    sy = AcademicYear.query.filter_by(year=year).first()
    if not sy:
        return False
    numbers = {t.number for t in sy.terms}
    return all(n in numbers for n in needed_terms)

def week_of_term_for(d: date, term: Term) -> int:
    # 1-based week number within the term
    return ((d - term.start_date).days // 7) + 1

def parse_time(hhmm: str, fallback: dtime = dtime(9, 0)) -> dtime:
    try:
        return datetime.strptime(hhmm, "%H:%M").time()
    except Exception:
        return fallback
