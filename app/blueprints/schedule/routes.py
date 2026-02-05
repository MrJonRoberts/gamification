from __future__ import annotations
from datetime import date, datetime, time, timedelta
import json
import subprocess
import sys
import os
import re
from typing import Dict, List, Any, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Body
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db, require_user, AnonymousUser
from app.models.schedule import Term, WeeklyPattern, Lesson, AcademicYear
from app.extensions import db
from app.models import Course
from app.services.orm_utils import first_model_attribute
from app.services.schedule_services import *
from app.services.qld_term_dates_scraper import *
from app.templating import render_template
from app.utils import flash
from app.config import settings

router = APIRouter(prefix="/courses", tags=["schedule"])

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

def _instance_data_path(filename: str) -> str:
    path = os.path.join(settings.ROOT_PATH, "instance")
    os.makedirs(path, exist_ok=True)
    return os.path.join(path, filename)

def _iso(y: int, d: str, m_name: str) -> str:
    m = MONTHS.get(m_name.capitalize())
    if not m:
        raise ValueError(f"Unknown month: {m_name!r}")
    return f"{y:04d}-{m:02d}-{int(d):02d}"

def split_and_normalise_terms(raw_text: str, year: int) -> List[Dict[str, Any]]:
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
    for t in out:
        if not t.get("name"):
            t["name"] = f"Term {t.get('number')}"
    return out

@router.get("/{course_id}/schedule/setup", response_class=HTMLResponse, name="schedule.schedule_setup")
def schedule_setup_form(
    course_id: int,
    request: Request,
    current_user: User | AnonymousUser = Depends(require_user),
    session: Session = Depends(get_db),
):
    course = session.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    default_year = course.year
    default_terms = SEMESTER_TO_TERMS.get(course.semester, [1, 2, 3, 4])
    patterns = (session.query(WeeklyPattern)
                .filter_by(course_id=course.id, is_active=True)
                .order_by(WeeklyPattern.day_of_week.asc()).all())
    return render_template("schedule/setup.html",
                           {
                               "request": request,
                               "course": course,
                               "default_year": default_year,
                               "default_terms": default_terms,
                               "patterns": patterns,
                               "current_user": current_user,
                           })

@router.post("/{course_id}/schedule/setup", name="schedule.schedule_setup_post")
def schedule_setup_action(
    course_id: int,
    request: Request,
    year: int = Form(None),
    term_mode: str = Form("use_semester"),
    terms: List[int] = Form([]),
    start_time_str: str = Form("09:00", alias="start_time"),
    end_time_str: str = Form("10:00", alias="end_time"),
    days: List[int] = Form([]),
    current_user: User | AnonymousUser = Depends(require_user),
    session: Session = Depends(get_db),
):
    course = session.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    year = year or course.year
    if term_mode == "use_semester":
        term_numbers = SEMESTER_TO_TERMS.get(course.semester, [1, 2, 3, 4])
    else:
        term_numbers = sorted(set(terms))

    if not term_numbers:
        flash(request, "Select at least one term.", "danger")
        return RedirectResponse(f"/courses/{course_id}/schedule/setup", status_code=303)

    if not ensure_year_has_terms(year, term_numbers):
        flash(request, f"Year {year} / terms {term_numbers} not configured yet.", "warning")
        return RedirectResponse(f"/admin/year/setup?year={year}&next=/courses/{course_id}/schedule/setup", status_code=303)

    start_time = parse_time(start_time_str, time(9, 0))
    end_time = parse_time(end_time_str, time(10, 0))

    if end_time <= start_time:
        flash(request, "End time must be after start time.", "danger")
        return RedirectResponse(f"/courses/{course_id}/schedule/setup", status_code=303)

    if not days:
        flash(request, "Choose at least one day of the week.", "danger")
        return RedirectResponse(f"/courses/{course_id}/schedule/setup", status_code=303)

    for dow in days:
        wp = session.query(WeeklyPattern).filter_by(course_id=course.id, day_of_week=dow).first()
        if not wp:
            wp = WeeklyPattern(course_id=course.id, day_of_week=dow)
            session.add(wp)
        wp.start_time = start_time
        wp.end_time = end_time
        wp.is_active = True
    session.flush()

    created = 0
    ts = get_terms_for(year, term_numbers)
    for term in ts:
        cursor = term.start_date
        while cursor <= term.end_date:
            if cursor.weekday() in days:
                exists = session.query(Lesson).filter_by(course_id=course.id, date=cursor).first()
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
                    session.add(lesson)
                    created += 1
            cursor += timedelta(days=1)

    session.commit()
    flash(request, f"Created {created} lesson(s) for {course.name}.", "success")
    return RedirectResponse(f"/courses/{course_id}/schedule", status_code=303)

@router.get("/year/setup", response_class=HTMLResponse, name="schedule.year_setup")
def year_setup(
    request: Request,
    year: int,
    next: str = "",
    current_user: User | AnonymousUser = Depends(require_user),
    session: Session = Depends(get_db),
):
    existing = session.query(AcademicYear).filter_by(year=year).first()
    json_path = _instance_data_path(f"term_dates_{year}.json")
    parsed = None
    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            parsed = json.load(f)

    return render_template(
        "schedule/year_setup.html",
        {
            "request": request,
            "year": year,
            "existing": existing,
            "parsed": parsed,
            "json_path": os.path.basename(json_path),
            "next_url": next,
            "current_user": current_user,
        }
    )

@router.post("/year/scrape", name="schedule.year_scrape")
def year_scrape(
    request: Request,
    year: int = Form(...),
    next_url: str = Form(""),
    current_user: User | AnonymousUser = Depends(require_user),
):
    data = None
    try:
        data = scrape_term_dates(SOURCE_URL)
    except Exception:
        candidate_paths = [
            os.path.join(settings.ROOT_PATH, "qld_term_dates_scraper.py"),
            "qld_term_dates_scraper.py",
        ]
        script_path = next((p for p in candidate_paths if os.path.exists(p)), None)
        if not script_path:
            flash(request, "Scraper script not found.", "danger")
            return RedirectResponse(f"/courses/year/setup?year={year}&next={next_url}", status_code=303)
        try:
            proc = subprocess.run([sys.executable, script_path], capture_output=True, text=True, check=True)
            data = json.loads(proc.stdout)
        except Exception as e:
            flash(request, f"Scrape failed: {e}", "danger")
            return RedirectResponse(f"/courses/year/setup?year={year}&next={next_url}", status_code=303)

    if not isinstance(data, dict):
        flash(request, "Unexpected scraper output.", "danger")
        return RedirectResponse(f"/courses/year/setup?year={year}&next={next_url}", status_code=303)

    source = data.get("source")
    last_updated = data.get("last_updated")
    raw_terms = []

    if "years" in data:
        block = next((y for y in data["years"] if int(y.get("year", 0)) == year), None)
        if not block:
            flash(request, f"Scraped data did not include {year}.", "warning")
            return RedirectResponse(f"/courses/year/setup?year={year}&next={next_url}", status_code=303)
        raw_terms = block.get("terms", [])
        source = block.get("source") or source
        last_updated = block.get("last_updated") or last_updated
    elif "terms" in data:
        if data.get("year") and int(data["year"]) != year:
            flash(request, f"Scraped payload was for {data['year']}, not {year}.", "warning")
            return RedirectResponse(f"/courses/year/setup?year={year}&next={next_url}", status_code=303)
        raw_terms = data.get("terms", [])
    else:
        flash(request, "No 'terms' found in scraper output.", "danger")
        return RedirectResponse(f"/courses/year/setup?year={year}&next={next_url}", status_code=303)

    ts = _normalise_terms_for_year(raw_terms, year)
    out_path = _instance_data_path(f"term_dates_{year}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "source": source,
            "last_updated": last_updated,
            "year": year,
            "terms": ts,
        }, f, ensure_ascii=False, indent=2)

    flash(request, f"Scraped and staged term dates for {year}.", "success")
    return RedirectResponse(f"/courses/year/setup?year={year}&next={next_url}", status_code=303)

@router.post("/year/confirm", name="schedule.year_confirm")
def year_confirm(
    request: Request,
    year: int = Form(...),
    next_url: str = Form(""),
    uploaded_json: str = Form(None, alias="__uploaded_json"),
    current_user: User | AnonymousUser = Depends(require_user),
    session: Session = Depends(get_db),
):
    json_path = _instance_data_path(f"term_dates_{year}.json")
    payload = None

    if uploaded_json:
        try:
            payload = json.loads(uploaded_json)
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception:
            payload = None

    if not payload:
        if not os.path.exists(json_path):
            flash(request, "No staged JSON to confirm.", "warning")
            return RedirectResponse(f"/courses/year/setup?year={year}&next={next_url}", status_code=303)
        with open(json_path, "r", encoding="utf-8") as f:
            payload = json.load(f)

    ay = session.query(AcademicYear).filter_by(year=year).first()
    if not ay:
        ay = AcademicYear(year=year)

    ay.source = payload.get("source") or ay.source
    lu = payload.get("last_updated")
    if lu:
        try:
            ay.last_updated = date.fromisoformat(lu)
        except Exception:
            ay.last_updated = None

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

    session.add(ay)
    session.commit()
    flash(request, f"Academic year {year} configured.", "success")
    return RedirectResponse(next_url or f"/courses/year/setup?year={year}", status_code=303)

@router.get("/{course_id}/schedule", response_class=HTMLResponse, name="schedule.course_schedule")
def course_schedule(
    course_id: int,
    request: Request,
    current_user: User | AnonymousUser = Depends(require_user),
    session: Session = Depends(get_db),
):
    course = session.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    target_year = getattr(course, "year", None) or date.today().year
    ay = session.query(AcademicYear).filter_by(year=target_year).first()
    ts = []
    if ay:
        ts = (session.query(Term)
                 .filter_by(academic_year_id=ay.id)
                 .order_by(Term.number.asc())
                 .all())

    lesson_date_col = first_model_attribute(Lesson, ["date"])
    lesson_time_col = first_model_attribute(Lesson, ["start_time", "starts_at"])
    order_columns = [col for col in (lesson_date_col, lesson_time_col) if col is not None]
    lessons_q = session.query(Lesson).filter_by(course_id=course.id)
    if order_columns:
        lessons_q = lessons_q.order_by(*order_columns)
    lessons = lessons_q.all()

    today = date.today()
    upcoming = []
    for l in lessons:
        l_date = getattr(l, "date", None)
        if l_date and l_date >= today:
            upcoming.append(l)
    upcoming = upcoming[:10]

    return render_template(
        'schedule/course_schedule.html',
        {
            "request": request,
            "course": course,
            "target_year": target_year,
            "ay": ay,
            "terms": ts,
            "lessons": lessons,
            "upcoming": upcoming,
            "current_user": current_user,
        }
    )
