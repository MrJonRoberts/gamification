from flask import Blueprint, render_template, request, redirect, url_for, flash, Response, current_app
from flask_login import login_required
from wtforms import StringField, validators, FileField
from werkzeug.utils import secure_filename
from flask_wtf import FlaskForm
from ...extensions import db
from ...models import User, BadgeGrant, Badge, Award, award_progress, user_total_points, Course
from sqlalchemy import func
import re
from PIL import Image
# import pandas as pd
import os, io, zipfile, pandas as pd, hashlib

ALLOWED_IMG_EXTS = {"png", "jpg", "jpeg", "webp"}
USER_AVATAR_FILES = ["dog_1.png","dog_2.png","dog_3.png","dog_4.png","dog_5.png"]  # app/static/avatars/
AVATAR_DIR = "static/avatars"   # put the avatar_*.png files here
def _img_ext_ok(name:str) -> bool:
    return "." in name and name.rsplit(".",1)[1].lower() in ALLOWED_IMG_EXTS

def _square_150(img: Image.Image) -> Image.Image:
    img = img.convert("RGBA")
    w, h = img.size
    side = min(w, h)
    x = (w - side)//2; y = (h - side)//2
    return img.crop((x, y, x+side, y+side)).resize((150,150), Image.LANCZOS)

def _save_user_avatar(basename: str, pil_img: Image.Image) -> str:
    """Save under static/avatars using a safe filename; return web path."""
    base = secure_filename(basename).lower() or "user"
    filename = f"{base}.png"
    save_dir = os.path.join(current_app.root_path, "static", "avatars")
    os.makedirs(save_dir, exist_ok=True)
    path = os.path.join(save_dir, filename)
    # avoid collision
    if os.path.exists(path):
        filename = f"{base}-{hashlib.md5(os.urandom(8)).hexdigest()[:6]}.png"
        path = os.path.join(save_dir, filename)
    pil_img.save(path, format="PNG", optimize=True)
    return f"/static/avatars/{filename}"

def _load_deterministic_avatar_for(key: str) -> Image.Image:
    """Pick a preset avatar based on a stable key (email/student_code/name)."""
    root = os.path.join(current_app.root_path, "static", "avatars")
    available = [f for f in USER_AVATAR_FILES if os.path.exists(os.path.join(root, f))]
    if not available:
        # gray placeholder
        return Image.new("RGBA", (150,150), (220,220,220,255))
    digest = hashlib.md5((key or "").strip().lower().encode("utf-8")).hexdigest()
    fp = os.path.join(root, available[int(digest,16)%len(available)])
    img = Image.open(fp); img.load()
    return img


def _require_admin() -> bool:
    from flask_login import current_user
    return current_user.is_authenticated and getattr(current_user, "role", "") == "admin"


students_bp = Blueprint("students", __name__)

class StudentForm(FlaskForm):
    student_code = StringField("Student Code", [validators.DataRequired(), validators.Length(max=32)])
    email = StringField("Email", [validators.DataRequired(), validators.Email()])
    first_name = StringField("First Name", [validators.DataRequired()])
    last_name = StringField("Last Name", [validators.DataRequired()])
    image = FileField("Profile Image (png/jpg/webp)")  # NEW

@students_bp.route("/")
@login_required
def list_students():
    students = User.query.filter_by(role="student").order_by(User.last_name, User.first_name).all()
    courses = Course.query.order_by(Course.year.desc(), Course.semester, Course.name).all()

    # --- Build award requirements: award_id -> set(badge_id)
    awards = Award.query.order_by(Award.name).all()
    award_requirements = {a.id: set(ab.badge_id for ab in a.award_badges) for a in awards}
    awards_total = len(awards)

    # --- Gather all badge grants for these students in one query
    student_ids = [s.id for s in students]
    earned_by_user = {sid: set() for sid in student_ids}
    if student_ids:
        rows = (
            db.session.query(BadgeGrant.user_id, BadgeGrant.badge_id)
            .filter(BadgeGrant.user_id.in_(student_ids))
            .all()
        )
        for uid, bid in rows:
            earned_by_user.setdefault(uid, set()).add(bid)

    # --- Compute summary per student
    award_summaries = {}
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

        percent = int(round(100 * total_earned_for_awards / total_required_badges)) if total_required_badges else 0
        award_summaries[s.id] = {
            "completed": completed,
            "total": awards_total,
            "in_progress": in_progress,
            "percent": percent,
        }

    return render_template(
        "students/list.html",
        students=students,
        courses=courses,
        award_summaries=award_summaries,
    )

@students_bp.route("/create", methods=["GET","POST"])
@login_required
def create_student():
    # Local imports to keep this function self-contained wherever it's placed
    from flask import current_app
    from PIL import Image
    import pandas as pd
    import zipfile, io, os

    # ---------- BULK BRANCH ----------
    if request.method == "POST" and request.form.get("action") == "bulk":
        file = request.files.get("file")
        images_zip = request.files.get("images_zip")  # optional

        if not file or file.filename == "":
            flash("Please upload a CSV or XLSX file.", "warning")
            return redirect(url_for("students.create_student", _anchor="bulk"))

        # Read CSV/XLSX into DataFrame
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

        has_code   = "student_code" in df.columns
        has_course = "course" in df.columns
        has_image  = "image_name" in df.columns  # optional

        # Build an index of images from ZIP (if supplied)
        icon_map = {}
        img_zf = None
        if images_zip and images_zip.filename.lower().endswith(".zip"):
            try:
                img_zip_bytes = images_zip.read()
                img_zf = zipfile.ZipFile(io.BytesIO(img_zip_bytes))
                for n in img_zf.namelist():
                    base = os.path.basename(n)
                    if base and base.lower().rsplit(".", 1)[-1] in {"png", "jpg", "jpeg", "webp"}:
                        icon_map[base.lower()] = n
            except Exception as e:
                flash(f"Could not read images ZIP: {e}", "danger")
                return redirect(url_for("students.create_student", _anchor="bulk"))

        created = enrolled = skipped = course_not_found = 0
        saved_files = []  # web paths of avatars saved during this bulk op (for cleanup on rollback)

        try:
            for _, row in df.iterrows():
                email = str(row.get("email", "")).strip().lower()
                first = str(row.get("first_name", "")).strip()
                last  = str(row.get("last_name", "")).strip()
                code  = (str(row.get("student_code", "")).strip() or None) if has_code else None
                course_text = str(row.get("course", "")).strip() if has_course else ""
                image_name  = str(row.get("image_name", "")).strip() if has_image else ""

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
                    # fill empty student_code if provided
                    if code and not u.student_code:
                        u.student_code = code

                # Avatar handling: try image from ZIP, else deterministic avatar
                pil = None
                if image_name and img_zf and image_name.lower() in icon_map:
                    try:
                        with img_zf.open(icon_map[image_name.lower()]) as fp:
                            img = Image.open(fp); img.load()
                            pil = img
                    except Exception:
                        pil = None

                if pil is None:
                    key = email or f"{first}-{last}"
                    pil = _load_deterministic_avatar_for(key)

                avatar_path = _save_user_avatar(email or code or f"{first}-{last}", _square_150(pil))
                saved_files.append(avatar_path)
                u.avatar = avatar_path

                # Optional enrolment
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
            # remove avatars saved during this attempt
            for web_path in saved_files:
                try:
                    fp = os.path.join(current_app.root_path, web_path.lstrip("/"))
                    if os.path.exists(fp):
                        os.remove(fp)
                except OSError:
                    pass
            flash(f"Bulk upload failed. No changes were saved. Details: {e}", "danger")
            return redirect(url_for("students.create_student", _anchor="bulk"))
        finally:
            if img_zf:
                try:
                    img_zf.close()
                except Exception:
                    pass

    # ---------- SINGLE CREATE BRANCH ----------
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

        # Optional uploaded photo → 150x150; else deterministic avatar
        pil = None
        file = request.files.get("image")
        if file and getattr(file, "filename", ""):
            try:
                img = Image.open(file.stream); img.load()
                pil = img
            except Exception:
                pil = None

        if pil is None:
            key = u.email or f"{u.first_name}-{u.last_name}"
            pil = _load_deterministic_avatar_for(key)

        u.avatar = _save_user_avatar(u.email or u.student_code or f"{u.first_name}-{u.last_name}", _square_150(pil))

        db.session.add(u)
        db.session.commit()
        flash("Student created.", "success")
        return redirect(url_for("students.list_students"))

    # GET (or failed validation)
    return render_template("students/form.html", form=form)


@students_bp.route("/<int:user_id>")
@login_required
def detail(user_id):
    student = User.query.get_or_404(user_id)
    if student.role != "student":
        flash("Not a student record.", "warning")
        return redirect(url_for("students.list_students"))

    # Most recent first; join to show badge details
    grants = (
        db.session.query(BadgeGrant, Badge)
        .join(Badge, BadgeGrant.badge_id == Badge.id)
        .filter(BadgeGrant.user_id == student.id)
        .order_by(BadgeGrant.issued_at.desc())
        .all()
    )
    total = user_total_points(student.id)
    return render_template("students/detail.html", student=student, grants=grants, total_points=total)

@students_bp.route("/<int:user_id>/awards")
@login_required
def awards_progress(user_id):
    student = User.query.get_or_404(user_id)

    awards = Award.query.order_by(Award.name).all()
    progress_list = []
    for a in awards:
        prog = award_progress(user_id=student.id, award_id=a.id)  # {badge_id: {...}}
        total = len(prog)
        earned = sum(1 for v in prog.values() if v["earned"])
        completed = (total > 0 and earned == total)
        completed_at = max(
            (v["earned_at"] for v in prog.values() if v["earned_at"]),
            default=None
        )
        progress_list.append({
            "award": a,
            "progress": prog,
            "total": total,
            "earned": earned,
            "completed": completed,
            "completed_at": completed_at,
        })

    total_points = user_total_points(student.id)
    return render_template(
        "students/awards.html",
        student=student,
        total_points=total_points,
        progress_list=progress_list
    )


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
        flash(f"Enrolled {student.full_name} in {course.name} {course.semester}{course.year}.", "success")
    else:
        flash(f"{student.full_name} is already enrolled in {course.name} {course.semester}{course.year}.", "info")
    return redirect(url_for("students.list_students"))


@students_bp.route("/bulk_template.csv")
@login_required
def bulk_template():
    csv_text = (
        "first_name,last_name,email,student_code,course\n"
        "Kai,Nguyen,kai@example.com,STU100,Yr6 Digital Tech S2 2025\n"
        "Mia,Singh,mia@example.com,STU101,12  # (Course ID also allowed)\n"
    )
    return Response(
        csv_text,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=students_bulk_template.csv"},
    )



@students_bp.route("/<int:user_id>/edit", methods=["GET","POST"])
@login_required
def edit_student(user_id):
    if not _require_admin():
        flash("Admin access required.", "danger")
        return redirect(url_for("students.list_students"))

    student = User.query.get_or_404(user_id)
    if student.role != "student":
        flash("Not a student record.", "warning")
        return redirect(url_for("students.list_students"))

    form = StudentForm(obj=student)

    if form.validate_on_submit():
        # Uniqueness checks (email, student_code)
        new_email = (form.email.data or "").strip().lower()
        clash = db.session.execute(
            db.select(User.id).where(User.email == new_email, User.id != student.id)
        ).first()
        if clash:
            flash("Email is already used by another user.", "warning")
            return render_template("students/edit.html", form=form, student=student)

        new_code = (form.student_code.data or "").strip() or None
        if new_code:
            code_clash = db.session.execute(
                db.select(User.id).where(User.student_code == new_code, User.id != student.id)
            ).first()
            if code_clash:
                flash("Student code is already used by another user.", "warning")
                return render_template("students/edit.html", form=form, student=student)

        # Update fields
        student.email = new_email
        student.student_code = new_code
        student.first_name = (form.first_name.data or "").strip()
        student.last_name  = (form.last_name.data or "").strip()

        # Optional: replace avatar if a new file uploaded
        file = request.files.get("image")
        if file and getattr(file, "filename", ""):
            try:
                img = Image.open(file.stream); img.load()
                processed = _square_150(img)
                new_avatar = _save_user_avatar(student.email or (student.student_code or f"{student.first_name}-{student.last_name}"), processed)

                # Clean up old avatar if it exists and changed
                old = student.avatar
                student.avatar = new_avatar
                if old and old != new_avatar:
                    try:
                        fp = os.path.join(current_app.root_path, old.lstrip("/"))
                        if os.path.exists(fp):
                            os.remove(fp)
                    except OSError:
                        pass
            except Exception:
                flash("Uploaded image is not a valid picture.", "danger")
                return render_template("students/edit.html", form=form, student=student)

        try:
            db.session.commit()
            flash("Student updated.", "success")
            return redirect(url_for("students.list_students"))
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception("Failed to update student: %s", e)
            flash("Could not update student due to a server error.", "danger")

    return render_template("students/edit.html", form=form, student=student)

def _find_course_from_text(text: str):
    """
    Accepts:
      - numeric ID, e.g. "12"
      - "Name S1 2025"  (exact match on name/semester/year, case-insensitive)
      - "Name - S1 2025" (dash optional)
    Returns Course or None.
    """
    if not text:
        return None
    t = str(text).strip()
    # ID
    if t.isdigit():
        return Course.query.get(int(t))
    # Try "Name S1 2025" or "Name - S1 2025"
    m = re.match(r"^(?P<name>.+?)\s*(?:-|–)?\s*(?P<sem>S[12])\s*(?P<year>\d{4})$", t, flags=re.IGNORECASE)
    if m:
        name = m.group("name").strip()
        sem = m.group("sem").upper()
        year = int(m.group("year"))
        return Course.query.filter(
            func.lower(Course.name) == name.lower(),
            Course.semester == sem,
            Course.year == year
        ).first()
    return None