from __future__ import annotations
import io
import os
import re
import zipfile

import pandas as pd
from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.dependencies import get_db, require_user, AnonymousUser
from app.models import (
    User,
    Role,
    Course,
    Award,
    BadgeGrant,
    Behaviour,
    PointLedger
)
from app.services.images import (
    allowed_image,
    open_image,
    square,
    save_png,
    user_fallback,
    remove_web_path,
)
from app.templating import render_template
from app.utils import flash

router = APIRouter(prefix="/students", tags=["students"])

def _has_role(user: User | AnonymousUser, *roles: str) -> bool:
    return getattr(user, "is_authenticated", False) and getattr(user, "role", "") in roles

def _student_or_redirect(session: Session, request: Request, user_id: int) -> User | RedirectResponse:
    student = session.get(User, user_id)
    if not student or student.role != "student":
        flash(request, "Not a student record.", "warning")
        return RedirectResponse("/students/", status_code=303)
    return student


def _admin_required_or_redirect(user: User | AnonymousUser, request: Request) -> RedirectResponse | None:
    if _has_role(user, "admin"):
        return None
    flash(request, "Admin access required.", "danger")
    return RedirectResponse("/students/", status_code=303)

def _find_course_from_text(session: Session, text: str | None) -> Course | None:
    if not text:
        return None
    t = str(text).strip()
    if t.isdigit():
        return session.get(Course, int(t))
    m = re.match(
        r"^(?P<name>.+?)\s*(?:-|–)?\s*(?P<sem>S[12])\s*(?P<year>\d{4})$",
        t,
        flags=re.IGNORECASE,
    )
    if m:
        name = m.group("name").strip()
        sem = m.group("sem").upper()
        year = int(m.group("year"))
        return (
            session.query(Course)
            .filter(
                func.lower(Course.name) == name.lower(),
                Course.semester == sem,
                Course.year == year,
            )
            .first()
        )
    return None

@router.get("/", response_class=HTMLResponse, name="students.list_students")
def list_students(
    request: Request,
    current_user: User | AnonymousUser = Depends(require_user),
    session: Session = Depends(get_db),
):
    """
    Lists all students and their award progress summaries.
    """
    students = (
        session.query(User)
        .join(User.roles)
        .filter(Role.name == "student")
        .order_by(User.last_name, User.first_name)
        .all()
    )
    courses = session.query(Course).order_by(Course.year.desc(), Course.semester, Course.name).all()

    awards = session.query(Award).order_by(Award.name).all()
    award_requirements = {
        a.id: {ab.badge_id for ab in a.award_badges} for a in awards
    }
    awards_total = len(awards)

    student_ids = [s.id for s in students]
    earned_by_user: dict[int, set[int]] = {sid: set() for sid in student_ids}
    if student_ids:
        rows = (
            session.query(BadgeGrant.user_id, BadgeGrant.badge_id)
            .filter(BadgeGrant.user_id.in_(student_ids))
            .all()
        )
        for uid, bid in rows:
            earned_by_user.setdefault(uid, set()).add(bid)

    award_summaries: dict[int, dict] = {}
    for s in students:
        earned = earned_by_user.get(s.id, set())
        completed = 0
        in_progress = 0
        total_required_badges = 0
        total_earned_for_awards = 0

        for req in award_requirements.values():
            if not req:
                continue
            total_required_badges += len(req)
            got = len(req & earned)
            total_earned_for_awards += got
            if got == len(req):
                completed += 1
            elif got > 0:
                in_progress += 1

        percent = (
            int(round(100 * total_earned_for_awards / total_required_badges))
            if total_required_badges
            else 0
        )
        award_summaries[s.id] = {
            "completed": completed,
            "total": awards_total,
            "in_progress": in_progress,
            "percent": percent,
        }

    behaviour_totals = {sid: 0 for sid in student_ids}
    if student_ids:
        rows = (
            session.query(Behaviour.user_id, func.coalesce(func.sum(Behaviour.delta), 0))
            .filter(Behaviour.user_id.in_(student_ids))
            .group_by(Behaviour.user_id)
            .all()
        )
        for uid, total in rows:
            behaviour_totals[uid] = int(total or 0)

    return render_template(
        "students/list.html",
        {
            "request": request,
            "students": students,
            "courses": courses,
            "award_summaries": award_summaries,
            "behaviour_totals": behaviour_totals,
            "current_user": current_user,
        },
    )

@router.post("/quick_enroll", name="students.quick_enroll")
def quick_enroll(
    request: Request,
    user_id: int = Form(...),
    course_id: int = Form(...),
    current_user: User | AnonymousUser = Depends(require_user),
    session: Session = Depends(get_db),
):
    """
    Enrolls a student in a course.
    """
    student = session.get(User, user_id)
    course = session.get(Course, course_id)
    if not student or not course:
        flash(request, "Invalid student or course.", "warning")
        return RedirectResponse("/students/", status_code=303)

    if student not in course.students:
        course.students.append(student)
        session.commit()
        flash(
            request,
            f"Enrolled {student.first_name} {student.last_name} in {course.display_name}.",
            "success",
        )
    else:
        flash(
            request,
            f"{student.first_name} {student.last_name} is already enrolled in {course.display_name}.",
            "info",
        )
    return RedirectResponse("/students/", status_code=303)

@router.get("/create", response_class=HTMLResponse, name="students.create_student")
def create_student_form(
    request: Request,
    current_user: User | AnonymousUser = Depends(require_user),
):
    """
    Renders the form to create a new student (single or bulk).
    """
    return render_template("students/form.html", {"request": request, "current_user": current_user})

@router.post("/create", name="students.create_student_post")
async def create_student_action(
    request: Request,
    action: str = Form(None),
    # Bulk fields
    file: UploadFile = File(None),
    images_zip: UploadFile = File(None),
    # Single fields
    student_code: str = Form(None),
    email: str = Form(None),
    first_name: str = Form(None),
    last_name: str = Form(None),
    image: UploadFile = File(None),
    current_user: User | AnonymousUser = Depends(require_user),
    session: Session = Depends(get_db),
):
    """
    Handles student creation, either single or via bulk upload.
    """
    if action == "bulk":
        if not file or not file.filename:
            flash(request, "Please upload a CSV or XLSX file.", "warning")
            return RedirectResponse("/students/create#bulk", status_code=303)

        try:
            contents = await file.read()
            fname = file.filename.lower()
            if fname.endswith(".csv"):
                df = pd.read_csv(io.BytesIO(contents))
            elif fname.endswith((".xlsx", ".xls")):
                df = pd.read_excel(io.BytesIO(contents))
            else:
                flash(request, "Unsupported file type. Please upload .csv or .xlsx", "danger")
                return RedirectResponse("/students/create#bulk", status_code=303)
        except Exception as e:
            flash(request, f"Could not read file: {e}", "danger")
            return RedirectResponse("/students/create#bulk", status_code=303)

        df.columns = [c.strip().lower() for c in df.columns]
        required = {"email", "first_name", "last_name"}
        missing = required - set(df.columns)
        if missing:
            flash(request, f"Missing required columns: {', '.join(sorted(missing))}", "danger")
            return RedirectResponse("/students/create#bulk", status_code=303)

        has_code = "student_code" in df.columns
        has_course = "course" in df.columns
        has_image = "image_name" in df.columns

        icon_map: dict[str, str] = {}
        zip_file: zipfile.ZipFile | None = None
        if images_zip and images_zip.filename and images_zip.filename.lower().endswith(".zip"):
            try:
                img_zip_bytes = await images_zip.read()
                zip_file = zipfile.ZipFile(io.BytesIO(img_zip_bytes))
                for n in zip_file.namelist():
                    base = os.path.basename(n)
                    if base and allowed_image(base):
                        icon_map[base.lower()] = n
            except Exception as e:
                if zip_file:
                    zip_file.close()
                flash(request, f"Could not read images ZIP: {e}", "danger")
                return RedirectResponse("/students/create#bulk", status_code=303)

        created = enrolled = skipped = course_not_found = 0
        saved_files: list[str] = []
        student_role = session.query(Role).filter_by(name="student").first()

        try:
            for _, row in df.iterrows():
                u_email = str(row.get("email", "")).strip().lower()
                u_first = str(row.get("first_name", "")).strip()
                u_last = str(row.get("last_name", "")).strip()
                u_code = (str(row.get("student_code", "")).strip() or None) if has_code else None
                course_text = str(row.get("course", "")).strip() if has_course else ""
                image_name = str(row.get("image_name", "")).strip() if has_image else ""

                if not (u_email and u_first and u_last):
                    skipped += 1
                    continue

                u = session.query(User).filter_by(email=u_email).first()
                if not u:
                    u = User(
                        student_code=u_code,
                        email=u_email,
                        first_name=u_first,
                        last_name=u_last,
                        registered_method="bulk",
                    )
                    u.set_password("ChangeMe123!")
                    if student_role:
                        u.roles.append(student_role)
                    session.add(u)
                    session.flush()
                    created += 1
                else:
                    if u_code and not u.student_code:
                        u.student_code = u_code

                pil = None
                if image_name and zip_file:
                    try:
                        member = icon_map.get(os.path.basename(image_name).lower())
                        if member:
                            with zip_file.open(member) as fp:
                                pil = open_image(fp)
                    except Exception:
                        pil = None
                if pil is None:
                    pil = user_fallback(u_email or f"{u_first}-{u_last}")

                avatar_path = save_png(
                    square(pil), "avatars", u_email or u_code or f"{u_first}-{u_last}"
                )
                saved_files.append(avatar_path)
                u.avatar = avatar_path

                if course_text:
                    course = _find_course_from_text(session, course_text)
                    if course:
                        if u not in course.students:
                            course.students.append(u)
                            enrolled += 1
                    else:
                        course_not_found += 1

            session.commit()
            if zip_file:
                zip_file.close()
            msg = f"Bulk upload complete: {created} created, {enrolled} enrolments, {skipped} skipped"
            if course_not_found:
                msg += f", {course_not_found} unknown course"
            flash(request, msg + ".", "success")
            return RedirectResponse("/students/", status_code=303)

        except Exception as e:
            session.rollback()
            if zip_file:
                zip_file.close()
            for web_path in saved_files:
                remove_web_path(web_path)
            flash(request, f"Bulk upload failed. No changes were saved. Details: {e}", "danger")
            return RedirectResponse("/students/create#bulk", status_code=303)

    else:
        # Single create
        if not email or not first_name or not last_name:
            flash(request, "Email, First Name, and Last Name are required.", "danger")
            return render_template("students/form.html", {"request": request, "current_user": current_user})

        normalized_email = (email or "").lower().strip()
        existing = session.query(User).filter(User.email == normalized_email).first()
        if existing:
            flash(request, "A user with that email already exists.", "warning")
            return render_template("students/form.html", {"request": request, "current_user": current_user})

        u = User(
            student_code=(student_code or "").strip() or None,
            email=normalized_email,
            first_name=(first_name or "").strip(),
            last_name=(last_name or "").strip(),
            registered_method="site",
        )
        u.set_password("ChangeMe123!")

        pil = None
        if image and image.filename:
            if not allowed_image(image.filename):
                flash(request, "Photo must be PNG/JPG/JPEG/WEBP.", "danger")
                return render_template("students/form.html", {"request": request, "current_user": current_user})
            try:
                contents = await image.read()
                pil = open_image(io.BytesIO(contents))
            except Exception:
                pil = None

        if pil is None:
            pil = user_fallback(u.email or f"{u.first_name}-{u.last_name}")

        u.avatar = save_png(
            square(pil),
            "avatars",
            u.email or u.student_code or f"{u.first_name}-{u.last_name}",
        )

        student_role = session.query(Role).filter_by(name="student").first()
        if student_role:
            u.roles.append(student_role)

        session.add(u)
        session.commit()
        flash(request, "Student created.", "success")
        return RedirectResponse("/students/", status_code=303)

@router.get("/{user_id}/edit", response_class=HTMLResponse, name="students.edit_student")
def edit_student_form(
    user_id: int,
    request: Request,
    current_user: User | AnonymousUser = Depends(require_user),
    session: Session = Depends(get_db),
):
    admin_redirect = _admin_required_or_redirect(current_user, request)
    if admin_redirect:
        return admin_redirect

    student = _student_or_redirect(session, request, user_id)
    if isinstance(student, RedirectResponse):
        return student

    return render_template("students/edit.html", {"request": request, "student": student, "current_user": current_user})

@router.post("/{user_id}/edit", name="students.edit_student_post")
async def edit_student_action(
    user_id: int,
    request: Request,
    email: str = Form(...),
    first_name: str = Form(...),
    last_name: str = Form(...),
    student_code: str = Form(None),
    image: UploadFile = File(None),
    current_user: User | AnonymousUser = Depends(require_user),
    session: Session = Depends(get_db),
):
    admin_redirect = _admin_required_or_redirect(current_user, request)
    if admin_redirect:
        return admin_redirect

    student = _student_or_redirect(session, request, user_id)
    if isinstance(student, RedirectResponse):
        return student

    new_email = email.strip().lower()
    clash = session.query(User).filter(User.email == new_email, User.id != student.id).first()
    if clash:
        flash(request, "Email is already used by another user.", "warning")
        return render_template("students/edit.html", {"request": request, "student": student, "current_user": current_user})

    new_code = (student_code or "").strip() or None
    if new_code:
        code_clash = session.query(User).filter(User.student_code == new_code, User.id != student.id).first()
        if code_clash:
            flash(request, "Student code is already used by another user.", "warning")
            return render_template("students/edit.html", {"request": request, "student": student, "current_user": current_user})

    student.email = new_email
    student.student_code = new_code
    student.first_name = first_name.strip()
    student.last_name = last_name.strip()

    if image and image.filename:
        if not allowed_image(image.filename):
            flash(request, "Photo must be PNG/JPG/JPEG/WEBP.", "danger")
            return render_template("students/edit.html", {"request": request, "student": student, "current_user": current_user})
        try:
            contents = await image.read()
            pil = open_image(io.BytesIO(contents))
            new_avatar = save_png(
                square(pil),
                "avatars",
                student.email or (student.student_code or f"{student.first_name}-{student.last_name}"),
            )
            old = student.avatar
            student.avatar = new_avatar
            if old and old != new_avatar:
                remove_web_path(old)
        except Exception:
            flash(request, "Uploaded image is not a valid picture.", "danger")
            return render_template("students/edit.html", {"request": request, "student": student, "current_user": current_user})

    session.commit()
    flash(request, "Student updated.", "success")
    return RedirectResponse("/students/", status_code=303)

@router.get("/{user_id}", response_class=HTMLResponse, name="students.detail")
def detail(
    user_id: int,
    request: Request,
    current_user: User | AnonymousUser = Depends(require_user),
    session: Session = Depends(get_db),
):
    student = session.get(User, user_id)
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    total_points = (
        session.query(func.coalesce(func.sum(PointLedger.delta), 0))
        .filter(PointLedger.user_id == user_id)
        .scalar()
        or 0
    )

    grants = (
        session.query(BadgeGrant)
        .options(
            joinedload(BadgeGrant.badge),
            joinedload(BadgeGrant.issued_by)
        )
        .filter(BadgeGrant.user_id == user_id)
        .order_by(BadgeGrant.issued_at.desc(), BadgeGrant.id.desc())
        .limit(50)
        .all()
    )

    return render_template(
        "students/detail.html",
        {
            "request": request,
            "student": student,
            "total_points": total_points,
            "grants": grants,
            "current_user": current_user,
        },
    )

@router.get("/{user_id}/awards", response_class=HTMLResponse, name="students.awards_progress")
def awards_progress(
    user_id: int,
    request: Request,
    current_user: User | AnonymousUser = Depends(require_user),
    session: Session = Depends(get_db),
):
    student = session.get(User, user_id)
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    awards = session.query(Award).order_by(Award.name).all()

    earned_dates = dict(
        session.query(BadgeGrant.badge_id, func.min(BadgeGrant.issued_at))
        .filter(BadgeGrant.user_id == user_id)
        .group_by(BadgeGrant.badge_id)
        .all()
    )

    rows = []
    for a in awards:
        badges = []
        complete = True
        for ab in a.award_badges:
            b = ab.badge
            dt = earned_dates.get(b.id)
            badges.append({"badge": b, "earned_at": dt})
            if dt is None:
                complete = False
        rows.append({"award": a, "badges": badges, "complete": complete})

    return render_template(
        "students/awards.html",
        {
            "request": request,
            "student": student,
            "rows": rows,
            "current_user": current_user,
        },
    )

@router.get("/bulk_template.csv", name="students.bulk_template")
def bulk_template(current_user: User | AnonymousUser = Depends(require_user)):
    csv_text = (
        "first_name,last_name,email,student_code,course,image_name\n"
        "Kai,Nguyen,kai@example.com,STU100,Yr6 Digital Tech S2 2025,kai.png\n"
        "Mia,Singh,mia@example.com,STU101,12, \n"
    )
    return Response(
        csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=students_bulk_template.csv"},
    )
