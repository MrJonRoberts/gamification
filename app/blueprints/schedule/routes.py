from datetime import date, datetime, time, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, current_app
from flask_login import login_required
from sqlalchemy import and_

import json
import subprocess
import sys
import os
import re
from typing import Dict, List, Any, Optional

from app.services.schedule_services import *

from app.models.schedule import Term, WeeklyPattern, Lesson, AcademicYear
from app.extensions import db
from app.models import Course
from app.services.orm_utils import first_model_attribute

from app.services.qld_term_dates_scraper import *

schedule_bp = Blueprint("schedule", __name__, url_prefix="/courses")



# Helper: pick the Lesson datetime attribute to read/order/set
LESSON_START_FIELDS = ["starts_at", "start_time", "start_at", "datetime", "date"]
SEMESTER_TO_TERMS = {
    "S1": [1, 2],
    "S2": [3, 4],
    "FULL": [1, 2, 3, 4],
}

MONTHS = {
    "January": 1, "February": 2, "March": 3, "April": 4, "May": 5, "June": 6,
    "July": 7, "August": 8, "September": 9, "October": 10, "November": 11, "December": 12
}

TERM_REGEX = re.compile(
    r"Term\s*(?P<num>[1-4])\s*:\s*"
    r"(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\s+)?(?P<sday>\d{1,2})\s+(?P<smon>[A-Za-z]+)\s+to\s+"
    r"(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\s+)?(?P<eday>\d{1,2})\s+(?P<emon>[A-Za-z]+)"
    r"\s*[—–-]?\s*(?P<w>\d+)\s*weeks",
    re.IGNORECASE
)


def get_lesson_start_attr():
    return first_model_attribute(Lesson, LESSON_START_FIELDS)

def lesson_order_column():
    return get_lesson_start_attr() or Lesson.id

def ensure_year_obj(year: int) -> AcademicYear | None:
    return AcademicYear.query.filter_by(year=year).first()

def get_term_range(ay: AcademicYear, term: int) -> tuple[date | None, date | None]:
    pairs = {
        1: (ay.term1_start, ay.term1_end),
        2: (ay.term2_start, ay.term2_end),
        3: (ay.term3_start, ay.term3_end),
        4: (ay.term4_start, ay.term4_end),
    }
    return pairs.get(term, (None, None))


def _instance_data_path(filename: str) -> str:
    os.makedirs(current_app.instance_path, exist_ok=True)
    return os.path.join(current_app.instance_path, filename)

def _safe_next(next_url: str, default_endpoint: str, **values):
    if next_url and next_url.startswith("/"):
        return next_url
    return url_for(default_endpoint, **values)

def _iso(y: int, d: str, m_name: str) -> str:
    m = MONTHS.get(m_name.capitalize())
    if not m:
        raise ValueError(f"Unknown month: {m_name!r}")
    return f"{y:04d}-{m:02d}-{int(d):02d}"

def split_and_normalise_terms(raw_text: str, year: int) -> List[Dict[str, Any]]:
    """Return a list of term dicts extracted from a raw combined line."""
    terms: List[Dict[str, Any]] = []
    hay = (raw_text or "").replace("\xa0", " ")
    for m in TERM_REGEX.finditer(hay):
        num = int(m.group("num"))
        start = _iso(year, m.group("sday"), m.group("smon"))
        end   = _iso(year, m.group("eday"), m.group("emon"))
        weeks = int(m.group("w"))
        terms.append({
            "number": num,
            "name": f"Term {num}",
            "start_date": start,
            "end_date": end,
            "weeks": weeks,
            "raw": m.group(0).strip(),
        })
    return terms

def _normalise_terms_for_year(raw_terms: List[Dict[str, Any]], year: int) -> List[Dict[str, Any]]:
    """Expand any combined lines and prefer entries with populated dates."""
    normalised: List[Dict[str, Any]] = []
    for t in raw_terms or []:
        raw = (t.get("raw") or "").strip()
        needs_split = (not t.get("start_date")) or (raw.lower().count("term ") > 1)
        if needs_split and raw:
            found = split_and_normalise_terms(raw, year)
            if found:
                normalised.extend(found)
                continue
        normalised.append(t)

    # Deduplicate by term number, prefer ones with start/end
    by_num: Dict[int, Dict[str, Any]] = {}
    for t in normalised:
        n = int(t.get("number")) if t.get("number") is not None else None
        if not n:
            continue
        if n in by_num:
            cur = by_num[n]
            cur_ok = bool(cur.get("start_date") and cur.get("end_date"))
            t_ok = bool(t.get("start_date") and t.get("end_date"))
            if t_ok and not cur_ok:
                by_num[n] = t
        else:
            by_num[n] = t

    out = sorted(by_num.values(), key=lambda x: int(x.get("number", 0)))
    # Ensure name exists
    for t in out:
        if not t.get("name"):
            t["name"] = f"Term {t.get('number')}"
    return out

# ---------- ROUTES ----------

@schedule_bp.route("/<int:course_id>/schedule/setup", methods=["GET", "POST"])
@login_required
def schedule_setup(course_id):
    course = Course.query.get_or_404(course_id)

    if request.method == "POST":
        year = int(request.form.get("year") or course.year)
        mode = request.form.get("term_mode", "use_semester")  # 'use_semester' or 'pick_terms'

        if mode == "use_semester":
            term_numbers = SEMESTER_TO_TERMS.get(course.semester, [1, 2, 3, 4])
        else:
            term_numbers = sorted({int(x) for x in request.form.getlist("terms")})

        if not term_numbers:
            flash("Select at least one term.", "danger")
            return redirect(request.url)

        # Ensure year & required terms exist
        if not ensure_year_has_terms(year, term_numbers):
            flash(f"Year {year} / terms {term_numbers} not configured yet.", "warning")
            return redirect(url_for("schedule.year_setup", year=year,
                                    next=url_for("schedule.schedule_setup", course_id=course.id)))

        # Time & days
        start_hhmm = request.form.get("start_time", "09:00")
        end_hhmm   = request.form.get("end_time", "10:00")
        start_time = parse_time(start_hhmm, time(9, 0))
        end_time = parse_time(end_hhmm, time(10, 0))

        if end_time <= start_time:
            flash("End time must be after start time.", "danger")
            return redirect(request.url)

        # Selected days of week (0=Mon..6=Sun)
        days = sorted({int(x) for x in request.form.getlist("days") if x.isdigit() and 0 <= int(x) <= 6})
        if not days:
            flash("Choose at least one day of the week.", "danger")
            return redirect(request.url)

        # Persist simple weekly patterns (one per DOW)
        for dow in days:
            wp = WeeklyPattern.query.filter_by(course_id=course.id, day_of_week=dow).first()
            if not wp:
                wp = WeeklyPattern(course_id=course.id, day_of_week=dow)
                db.session.add(wp)
            wp.start_time = start_time
            wp.end_time = end_time
            wp.is_active = True
        db.session.flush()

        created = 0
        # Generate lessons for each selected term
        terms = get_terms_for(year, term_numbers)
        for term in terms:
            cursor = term.start_date
            while cursor <= term.end_date:
                if cursor.weekday() in days:
                    # Uniqueness guard (unique on course_id + date)
                    exists = Lesson.query.filter_by(course_id=course.id, date=cursor).first()
                    if not exists:
                        lesson = Lesson(
                            course_id=course.id,
                            term_id=term.id,
                            date=cursor,
                            week_of_term=week_of_term_for(cursor, term),
                            status="SCHEDULED",
                            start_time=start_time,
                            end_time=end_time,
                        )
                        db.session.add(lesson)
                        created += 1
                cursor += timedelta(days=1)

        db.session.commit()
        flash(f"Created {created} lesson(s) for {course.name}.", "success")
        return redirect(url_for("schedule.course_schedule", course_id=course.id))

    # GET
    default_year = course.year
    default_terms = SEMESTER_TO_TERMS.get(course.semester, [1, 2, 3, 4])
    patterns = (WeeklyPattern.query
                .filter_by(course_id=course.id, is_active=True)
                .order_by(WeeklyPattern.day_of_week.asc()).all())
    return render_template("schedule/setup.html",
                           course=course,
                           default_year=default_year,
                           default_terms=default_terms,
                           patterns=patterns)

# Year setup flow
# GET  /courses/year/setup?year=2025&next=/courses/3/schedule/setup
# POST /courses/year/scrape
# POST /courses/year/confirm

@schedule_bp.get("/year/setup")
@login_required
def year_setup():
    """Render the year configuration page with preview if a staged JSON exists."""
    try:
        year = int(request.args.get("year", ""))
    except ValueError:
        abort(400, "year is required")

    next_url = request.args.get("next", "")

    existing = AcademicYear.query.filter_by(year=year).first()
    json_path = _instance_data_path(f"term_dates_{year}.json")
    parsed = None
    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            parsed = json.load(f)

    return render_template(
        "schedule/year_setup.html",
        year=year,
        existing=existing,
        parsed=parsed,
        json_path=os.path.basename(json_path),
        next_url=next_url,
    )

@schedule_bp.post("/year/scrape")
@login_required
def year_scrape():
    """Run the scraper, normalise output, and stage a year JSON for preview."""
    try:
        year = int(request.form.get("year", ""))
    except ValueError:
        abort(400, "year is required")

    next_url = request.form.get("next_url", "")

    # Try importing a function; fall back to executing a script.
    data: Optional[Dict[str, Any]] = None
    try:
        # reusable module version, prefer importing it:
        # from app.utils.qld_term_dates_scraper import scrape_term_dates, SOURCE_URL
        data = scrape_term_dates(SOURCE_URL)
        # raise ImportError  # force fallback if you don't have the module
    except Exception:
        # Fallback: call a standalone script (project root or on PATH)
        candidate_paths = [
            os.path.join(current_app.root_path, "qld_term_dates_scraper.py"),
            os.path.join(current_app.root_path, "..", "qld_term_dates_scraper.py"),
            "qld_term_dates_scraper.py",
        ]
        script_path = next((p for p in candidate_paths if os.path.exists(p)), None)
        if not script_path:
            flash("Scraper script not found. Place qld_term_dates_scraper.py in your project root.", "danger")
            return redirect(url_for("schedule.year_setup", year=year, next=next_url))
        try:
            proc = subprocess.run([sys.executable, script_path], capture_output=True, text=True, check=True)
            data = json.loads(proc.stdout)
        except Exception as e:
            current_app.logger.exception("Scrape failed")
            flash(f"Scrape failed: {e}", "danger")
            return redirect(url_for("schedule.year_setup", year=year, next=next_url))

    if not isinstance(data, dict):
        flash("Unexpected scraper output.", "danger")
        return redirect(url_for("schedule.year_setup", year=year, next=next_url))

    # Accept either {"years":[{year,terms...}], ...} or {"year":2025,"terms":[...],...}
    source = data.get("source")
    last_updated = data.get("last_updated")
    raw_terms: List[Dict[str, Any]] = []

    if "years" in data:
        block = next((y for y in data["years"] if int(y.get("year", 0)) == year), None)
        if not block:
            flash(f"Scraped data did not include {year}.", "warning")
            return redirect(url_for("schedule.year_setup", year=year, next=next_url))
        raw_terms = block.get("terms", [])
        # allow per-block metadata to override
        source = block.get("source") or source
        last_updated = block.get("last_updated") or last_updated
    elif "terms" in data:
        if data.get("year") and int(data["year"]) != year:
            flash(f"Scraped payload was for {data['year']}, not {year}.", "warning")
            return redirect(url_for("schedule.year_setup", year=year, next=next_url))
        raw_terms = data.get("terms", [])
    else:
        flash("No 'terms' found in scraper output.", "danger")
        return redirect(url_for("schedule.year_setup", year=year, next=next_url))

    # 🔧 Normalise combined lines & missing dates (e.g., Term 1 & Term 2 on same line)
    terms = _normalise_terms_for_year(raw_terms, year)

    # Stage to instance/
    out_path = _instance_data_path(f"term_dates_{year}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "source": source,
            "last_updated": last_updated,
            "year": year,
            "terms": terms,
        }, f, ensure_ascii=False, indent=2)

    flash(f"Scraped and staged term dates for {year}. Review below.", "success")
    return redirect(url_for("schedule.year_setup", year=year, next=next_url))

@schedule_bp.post("/year/confirm")
@login_required
def year_confirm():
    """Commit staged JSON to the DB, idempotently replacing terms, then follow `next`."""
    try:
        year = int(request.form.get("year", ""))
    except ValueError:
        abort(400, "year is required")

    next_url = request.form.get("next_url", "")
    json_path = _instance_data_path(f"term_dates_{year}.json")
    payload: Optional[Dict[str, Any]] = None

    # (Optional) allow manual JSON upload via hidden field
    uploaded = request.form.get("__uploaded_json")
    if uploaded:
        try:
            payload = json.loads(uploaded)
            # Save what the user uploaded, so a refresh still previews the same
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception:
            payload = None

    if not payload:
        if not os.path.exists(json_path):
            flash("No staged JSON to confirm. Please run the scraper first.", "warning")
            return redirect(url_for("schedule.year_setup", year=year, next=next_url))
        with open(json_path, "r", encoding="utf-8") as f:
            payload = json.load(f)

    # Upsert year & terms
    ay = AcademicYear.query.filter_by(year=year).first()
    if not ay:
        ay = AcademicYear(year=year)

    ay.source = payload.get("source") or ay.source
    lu = payload.get("last_updated")
    if lu:
        try:
            ay.last_updated = date.fromisoformat(lu)
        except Exception:
            ay.last_updated = None

    # Clear and replace terms
    ay.terms.clear()
    for t in payload.get("terms", []):
        sd = t.get("start_date")
        ed = t.get("end_date")
        term = Term(
            number=int(t.get("number")),
            name=t.get("name") or f"Term {t.get('number')}",
            start_date=date.fromisoformat(sd) if sd else None,
            end_date=date.fromisoformat(ed) if ed else None,
            weeks=int(t.get("weeks")) if t.get("weeks") not in (None, "") else None,
            raw=t.get("raw"),
        )
        ay.terms.append(term)

    db.session.add(ay)
    db.session.commit()

    flash(f"Academic year {year} configured.", "success")
    return redirect(_safe_next(next_url, "schedule.year_setup", year=year))


@schedule_bp.get('/<int:course_id>/schedule', endpoint='course_schedule')
@login_required
def course_schedule(course_id):
    """
    Read-only view of a course's schedule.
    - Shows 'Configure Year' CTA if the academic year isn't set up yet.
    - Lists upcoming lessons (next 10) and the full schedule.
    """
    course = Course.query.get_or_404(course_id)

    # Pick the target academic year from the course if available, else current year.
    target_year = getattr(course, "year", None) or date.today().year

    ay = AcademicYear.query.filter_by(year=target_year).first()
    terms = []
    if ay:
        terms = (Term.query
                 .filter_by(academic_year_id=ay.id)
                 .order_by(Term.number.asc())
                 .all())

    # Load lessons for this course; be defensive about optional fields.
    lesson_date_col = first_model_attribute(Lesson, ["date"])
    lesson_time_col = first_model_attribute(Lesson, ["start_time", "starts_at"])
    order_columns = [col for col in (lesson_date_col, lesson_time_col) if col is not None]
    lessons_q = Lesson.query.filter_by(course_id=course.id)
    if order_columns:
        lessons_q = lessons_q.order_by(*order_columns)
    lessons = lessons_q.all()

    # Compute a simple "upcoming" list from today (if Lesson has a date field)
    today = date.today()
    upcoming = []
    for l in lessons:
        l_date = getattr(l, "date", None)
        if l_date and l_date >= today:
            upcoming.append(l)
    upcoming = upcoming[:10]

    return render_template(
        'schedule/course_schedule.html',
        course=course,
        target_year=target_year,
        ay=ay,
        terms=terms,
        lessons=lessons,
        upcoming=upcoming,
    )
