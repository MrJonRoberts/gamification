# app/blueprints/students/routes.py

from __future__ import annotations
from sqlalchemy.orm import joinedload
import io
import os
import re
import zipfile

import pandas as pd
from flask import (
    Blueprint,
    Response,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import func

from ...extensions import db
from ...models import (
    User,
    Course,
    Award,
    AwardBadge,
    BadgeGrant,
    PointLedger,
    Behaviour
)
from ...services.images import (
    allowed_image,
    open_image,
    square,
    save_png,
    user_fallback,
    remove_web_path,
)
from .forms import StudentForm  # adjust if your form lives elsewhere

students_bp = Blueprint("students", __name__)

# -----------------------------
# Helpers (tiny, non-dup)
# -----------------------------
def _has_role(*roles: str) -> bool:
    return current_user.is_authenticated and getattr(current_user, "role", "") in roles


def _find_course_from_text(text: str | None) -> Course | None:
    """
    Accepts:
      - numeric ID, e.g., "12"
      - "Name S1 2025" or "Name - S1 2025" (case-insensitive)
    """
    if not text:
        return None
    t = str(text).strip()
    if t.isdigit():
        return Course.query.get(int(t))
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
            Course.query.filter(
                func.lower(Course.name) == name.lower(),
                Course.semester == sem,
                Course.year == year,
            )
            .limit(1)
            .first()
        )
    return None


# -----------------------------
# List + Awards summary
# -----------------------------
@students_bp.route("/")
@login_required
def list_students():
    students = (
        User.query.filter_by(role="student")
        .order_by(User.last_name, User.first_name)
        .all()
    )
    courses = Course.query.order_by(Course.year.desc(), Course.semester, Course.name).all()

    # Build award requirements once: award_id -> set(badge_id)
    awards = Award.query.order_by(Award.name).all()
    award_requirements = {
        a.id: {ab.badge_id for ab in a.award_badges} for a in awards
    }
    awards_total = len(awards)

    # All badge grants for these students in one go
    student_ids = [s.id for s in students]
    earned_by_user: dict[int, set[int]] = {sid: set() for sid in student_ids}
    if student_ids:
        rows = (
            db.session.query(BadgeGrant.user_id, BadgeGrant.badge_id)
            .filter(BadgeGrant.user_id.in_(student_ids))
            .all()
        )
        for uid, bid in rows:
            earned_by_user.setdefault(uid, set()).add(bid)

    # Compute a compact summary per student
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
        # NEW: behaviour totals per student
    student_ids = [s.id for s in students]
    behaviour_totals = {sid: 0 for sid in student_ids}
    if student_ids:
        rows = (
            db.session.query(Behaviour.user_id, func.coalesce(func.sum(Behaviour.delta), 0))
            .filter(Behaviour.user_id.in_(student_ids))
            .group_by(Behaviour.user_id)
            .all()
        )
        for uid, total in rows:
            behaviour_totals[uid] = int(total or 0)

    return render_template(
        "students/list.html",
        students=students,
        courses=courses,
        award_summaries=award_summaries,
        behaviour_totals=behaviour_totals,  # <-- pass to template
    )



# -----------------------------
# Quick enrol into a course
# -----------------------------
@students_bp.post("/quick_enroll")
@login_required
def quick_enroll():
    user_id = request.form.get("user_id", type=int)
    course_id = request.form.get("course_id", type=int)
    if not user_id or not course_id:
        flash("Please select a student and a course.", "warning")
        return redirect(url_for("students.list_students"))

    student = User.query.get_or_404(user_id)
    course = Course.query.get_or_404(course_id)

    if student not in course.students:
        course.students.append(student)
        db.session.commit()
        flash(
            f"Enrolled {student.first_name} {student.last_name} in {course.name} {course.semester}{course.year}.",
            "success",
        )
    else:
        flash(
            f"{student.first_name} {student.last_name} is already enrolled in {course.name} {course.semester}{course.year}.",
            "info",
        )
    return redirect(url_for("students.list_students"))


# -----------------------------
# Create (single + bulk)
# -----------------------------
@students_bp.route("/create", methods=["GET", "POST"])
@login_required
def create_student():
    # ----- Bulk branch -----
    if request.method == "POST" and request.form.get("action") == "bulk":
        file = request.files.get("file")
        images_zip = request.files.get("images_zip")  # optional

        if not file or file.filename == "":
            flash("Please upload a CSV or XLSX file.", "warning")
            return redirect(url_for("students.create_student", _anchor="bulk"))

        # Load DataFrame
        try:
            fname = file.filename.lower()
            if fname.endswith(".csv"):
                df = pd.read_csv(file)
            elif fname.endswith((".xlsx", ".xls")):
                df = pd.read_excel(file)
            else:
                flash("Unsupported file type. Please upload .csv or .xlsx", "danger")
                return redirect(url_for("students.create_student", _anchor="bulk"))
        except Exception as e:
            flash(f"Could not read file: {e}", "danger")
            return redirect(url_for("students.create_student", _anchor="bulk"))

        # Normalize/validate columns
        df.columns = [c.strip().lower() for c in df.columns]
        required = {"email", "first_name", "last_name"}
        missing = required - set(df.columns)
        if missing:
            flash(f"Missing required columns: {', '.join(sorted(missing))}", "danger")
            return redirect(url_for("students.create_student", _anchor="bulk"))

        has_code = "student_code" in df.columns
        has_course = "course" in df.columns
        has_image = "image_name" in df.columns

        # Optional images ZIP → build basename index
        icon_map: dict[str, str] = {}
        img_zip_bytes: bytes | None = None
        if images_zip and images_zip.filename.lower().endswith(".zip"):
            try:
                img_zip_bytes = images_zip.read()
                with zipfile.ZipFile(io.BytesIO(img_zip_bytes)) as zf:
                    for n in zf.namelist():
                        base = os.path.basename(n)
                        if base and allowed_image(base):
                            icon_map[base.lower()] = n
            except Exception as e:
                flash(f"Could not read images ZIP: {e}", "danger")
                return redirect(url_for("students.create_student", _anchor="bulk"))

        created = enrolled = skipped = course_not_found = 0
        saved_files: list[str] = []

        try:
            for _, row in df.iterrows():
                email = str(row.get("email", "")).strip().lower()
                first = str(row.get("first_name", "")).strip()
                last = str(row.get("last_name", "")).strip()
                code = (
                    (str(row.get("student_code", "")).strip() or None) if has_code else None
                )
                course_text = str(row.get("course", "")).strip() if has_course else ""
                image_name = str(row.get("image_name", "")).strip() if has_image else ""

                if not (email and first and last):
                    skipped += 1
                    continue

                u = User.query.filter_by(email=email).first()
                if not u:
                    u = User(
                        student_code=code,
                        email=email,
                        first_name=first,
                        last_name=last,
                        role="student",
                        registered_method="bulk",
                    )
                    u.set_password("ChangeMe123!")
                    db.session.add(u)
                    db.session.flush()
                    created += 1
                else:
                    if code and not u.student_code:
                        u.student_code = code

                # Avatar: prefer image from ZIP if present; else deterministic
                pil = None
                if image_name and img_zip_bytes:
                    try:
                        with zipfile.ZipFile(io.BytesIO(img_zip_bytes)) as zf:
                            member = icon_map.get(os.path.basename(image_name).lower())
                            if member:
                                with zf.open(member) as fp:
                                    pil = open_image(fp)
                    except Exception:
                        pil = None
                if pil is None:
                    pil = user_fallback(email or f"{first}-{last}")

                avatar_path = save_png(
                    square(pil), "avatars", email or code or f"{first}-{last}"
                )
                saved_files.append(avatar_path)
                u.avatar = avatar_path

                if course_text:
                    course = _find_course_from_text(course_text)
                    if course:
                        if u not in course.students:
                            course.students.append(u)
                            enrolled += 1
                    else:
                        course_not_found += 1

            db.session.commit()
            msg = f"Bulk upload complete: {created} created, {enrolled} enrolments, {skipped} skipped"
            if course_not_found:
                msg += f", {course_not_found} unknown course"
            flash(msg + ".", "success")
            return redirect(url_for("students.list_students"))

        except Exception as e:
            db.session.rollback()
            for web_path in saved_files:
                remove_web_path(web_path)
            flash(f"Bulk upload failed. No changes were saved. Details: {e}", "danger")
            return redirect(url_for("students.create_student", _anchor="bulk"))

    # ----- Single-create branch -----
    form = StudentForm()
    if form.validate_on_submit():
        u = User(
            role="student",
            student_code=(form.student_code.data or "").strip() or None,
            email=(form.email.data or "").lower().strip(),
            first_name=(form.first_name.data or "").strip(),
            last_name=(form.last_name.data or "").strip(),
            registered_method="site",
        )
        u.set_password("ChangeMe123!")

        # Optional photo upload → else deterministic avatar
        pil = None
        file = request.files.get("image")
        if file and getattr(file, "filename", ""):
            if not allowed_image(file.filename):
                flash("Photo must be PNG/JPG/JPEG/WEBP.", "danger")
                return render_template("students/form.html", form=form)
            try:
                pil = open_image(file.stream)
            except Exception:
                pil = None
        if pil is None:
            pil = user_fallback(u.email or f"{u.first_name}-{u.last_name}")

        u.avatar = save_png(
            square(pil),
            "avatars",
            u.email or u.student_code or f"{u.first_name}-{u.last_name}",
        )

        db.session.add(u)
        db.session.commit()
        flash("Student created.", "success")
        return redirect(url_for("students.list_students"))

    return render_template("students/form.html", form=form)


# -----------------------------
# Edit (admin only)
# -----------------------------
@students_bp.route("/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
def edit_student(user_id: int):
    if not _has_role("admin"):
        flash("Admin access required.", "danger")
        return redirect(url_for("students.list_students"))

    student = User.query.get_or_404(user_id)
    if student.role != "student":
        flash("Not a student record.", "warning")
        return redirect(url_for("students.list_students"))

    form = StudentForm(obj=student)

    if form.validate_on_submit():
        # Email uniqueness
        new_email = (form.email.data or "").strip().lower()
        clash = db.session.execute(
            db.select(User.id).where(User.email == new_email, User.id != student.id)
        ).first()
        if clash:
            flash("Email is already used by another user.", "warning")
            return render_template("students/edit.html", form=form, student=student)

        # Student code uniqueness
        new_code = (form.student_code.data or "").strip() or None
        if new_code:
            code_clash = db.session.execute(
                db.select(User.id).where(User.student_code == new_code, User.id != student.id)
            ).first()
            if code_clash:
                flash("Student code is already used by another user.", "warning")
                return render_template("students/edit.html", form=form, student=student)

        student.email = new_email
        student.student_code = new_code
        student.first_name = (form.first_name.data or "").strip()
        student.last_name = (form.last_name.data or "").strip()

        # Optional avatar replacement
        file = request.files.get("image")
        if file and getattr(file, "filename", ""):
            if not allowed_image(file.filename):
                flash("Photo must be PNG/JPG/JPEG/WEBP.", "danger")
                return render_template("students/edit.html", form=form, student=student)
            try:
                pil = open_image(file.stream)
            except Exception:
                flash("Uploaded image is not a valid picture.", "danger")
                return render_template("students/edit.html", form=form, student=student)

            new_avatar = save_png(
                square(pil),
                "avatars",
                student.email or (student.student_code or f"{student.first_name}-{student.last_name}"),
            )
            old = student.avatar
            student.avatar = new_avatar
            if old and old != new_avatar:
                remove_web_path(old)

        try:
            db.session.commit()
            flash("Student updated.", "success")
            return redirect(url_for("students.list_students"))
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception("Failed to update student: %s", e)
            flash("Could not update student due to a server error.", "danger")

    return render_template("students/edit.html", form=form, student=student)


# -----------------------------
# Detail + Awards progress pages
# -----------------------------
@students_bp.route("/<int:user_id>")
@login_required
def detail(user_id: int):
    student = User.query.get_or_404(user_id)

    # Total points for the student
    total_points = (
        db.session.query(func.coalesce(func.sum(PointLedger.delta), 0))
        .filter(PointLedger.user_id == user_id)
        .scalar()
        or 0
    )

    # Eager-load related badge (and issuer if you have that relationship)
    grants = (
        db.session.query(BadgeGrant)
        .options(
            joinedload(BadgeGrant.badge),
            joinedload(BadgeGrant.issued_by)  # ← remove this line if you don't have `issued_by` relationship
        )
        .filter(BadgeGrant.user_id == user_id)
        .order_by(BadgeGrant.issued_at.desc(), BadgeGrant.id.desc())
        .limit(50)
        .all()
    )

    return render_template(
        "students/detail.html",
        student=student,
        total_points=total_points,
        grants=grants,
    )

@students_bp.route("/<int:user_id>/awards")
@login_required
def awards_progress(user_id: int):
    student = User.query.get_or_404(user_id)

    # Load all awards with required badges
    awards = Award.query.order_by(Award.name).all()
    req_map = {a.id: [ab.badge for ab in a.award_badges] for a in awards}

    # All earned badges for student with dates
    earned_dates = dict(
        db.session.query(BadgeGrant.badge_id, func.min(BadgeGrant.issued_at))
        .filter(BadgeGrant.user_id == user_id)
        .group_by(BadgeGrant.badge_id)
        .all()
    )

    # Build view model
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

    return render_template("students/awards_progress.html", student=student, rows=rows)


# -----------------------------
# Bulk CSV template
# -----------------------------
@students_bp.route("/bulk_template.csv")
@login_required
def bulk_template():
    csv_text = (
        "first_name,last_name,email,student_code,course,image_name\n"
        "Kai,Nguyen,kai@example.com,STU100,Yr6 Digital Tech S2 2025,kai.png\n"
        "Mia,Singh,mia@example.com,STU101,12, \n"
    )
    return Response(
        csv_text,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=students_bulk_template.csv"},
    )
