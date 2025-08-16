# app/blueprints/badges/routes.py

from __future__ import annotations

import csv
import io
import os
import zipfile

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
    Response,
)
from flask_login import current_user, login_required
from sqlalchemy import func

from ...extensions import db
from ...models import Badge, BadgeGrant, User
from ...services.images import (
    allowed_image,
    open_image,
    square,
    save_png,
    badge_fallback,
    remove_web_path,
)
from ...services.awarding import grant_badge
from .forms import BadgeForm  # adjust if your form is elsewhere

badges_bp = Blueprint("badges", __name__)


# -----------------------------
# Small role helpers
# -----------------------------
def _has_role(*roles: str) -> bool:
    return current_user.is_authenticated and getattr(current_user, "role", "") in roles


# -----------------------------
# List
# -----------------------------
@badges_bp.route("/")
@login_required
def list_badges():
    badges = Badge.query.order_by(Badge.name.asc()).all()
    return render_template("badges/list.html", badges=badges)


# -----------------------------
# Create
# -----------------------------
@badges_bp.route("/create", methods=["GET", "POST"])
@login_required
def create_badge():
    if not _has_role("admin", "issuer"):
        flash("Only staff can create badges.", "danger")
        return redirect(url_for("badges.list_badges"))

    form = BadgeForm()
    if form.validate_on_submit():
        name = (form.name.data or "").strip()

        # Uniqueness
        exists = db.session.execute(
            db.select(Badge.id).where(func.lower(Badge.name) == name.lower())
        ).first()
        if exists:
            flash("A badge with that name already exists.", "warning")
            return render_template("badges/form.html", form=form)

        # Icon: uploaded or fallback avatar
        file = form.icon.data
        pil = None
        if file and getattr(file, "filename", ""):
            if not allowed_image(file.filename):
                flash("Icon must be PNG/JPG/JPEG/WEBP.", "danger")
                return render_template("badges/form.html", form=form)
            try:
                pil = open_image(file.stream)
            except ValueError:
                flash("The uploaded file isn’t a valid image.", "danger")
                return render_template("badges/form.html", form=form)
        else:
            pil = badge_fallback(name)

        icon_path = save_png(square(pil), "icons", name)

        try:
            b = Badge(
                name=name,
                description=(form.description.data or "").strip() or None,
                icon=icon_path,
                points=form.points.data or 0,
                created_by_id=current_user.id,
            )
            db.session.add(b)
            db.session.commit()
            flash("Badge created.", "success")
            return redirect(url_for("badges.list_badges"))
        except Exception as e:
            db.session.rollback()
            remove_web_path(icon_path)
            current_app.logger.exception("Error creating badge: %s", e)
            flash("Could not create the badge due to a server error.", "danger")

    return render_template("badges/form.html", form=form)


# -----------------------------
# Edit (admin only)
# -----------------------------
@badges_bp.route("/edit/<int:badge_id>", methods=["GET", "POST"])
@login_required
def edit_badge(badge_id: int):
    if not _has_role("admin"):
        flash("Admin access required.", "danger")
        return redirect(url_for("badges.list_badges"))

    badge = Badge.query.get_or_404(badge_id)
    form = BadgeForm(obj=badge)

    if form.validate_on_submit():
        new_name = (form.name.data or "").strip()

        # Uniqueness excluding self
        clash = db.session.execute(
            db.select(Badge.id).where(
                func.lower(Badge.name) == new_name.lower(), Badge.id != badge.id
            )
        ).first()
        if clash:
            flash("Another badge already uses that name.", "warning")
            return render_template("badges/edit.html", form=form, badge=badge)

        old_icon = badge.icon

        # Update fields
        badge.name = new_name
        badge.description = (form.description.data or "").strip() or None
        badge.points = form.points.data or 0

        # Optional icon replacement
        file = form.icon.data
        if file and getattr(file, "filename", ""):
            if not allowed_image(file.filename):
                flash("Icon must be PNG/JPG/JPEG/WEBP.", "danger")
                return render_template("badges/edit.html", form=form, badge=badge)
            try:
                pil = open_image(file.stream)
            except ValueError:
                flash("Uploaded icon is not a valid image.", "danger")
                return render_template("badges/edit.html", form=form, badge=badge)

            new_icon = save_png(square(pil), "icons", badge.name)
            badge.icon = new_icon

        try:
            db.session.commit()
            # Clean old icon if changed
            if old_icon and badge.icon != old_icon:
                remove_web_path(old_icon)

            flash("Badge updated.", "success")
            return redirect(url_for("badges.list_badges"))
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception("Failed to edit badge: %s", e)
            flash("Could not update the badge due to a server error.", "danger")

    return render_template("badges/edit.html", form=form, badge=badge)


# -----------------------------
# Grant (issuer/admin)
# -----------------------------
@badges_bp.route("/grant/<int:badge_id>", methods=["GET", "POST"])
@login_required
def grant(badge_id: int):
    if not _has_role("admin", "issuer"):
        flash("Only staff can grant badges.", "danger")
        return redirect(url_for("badges.list_badges"))

    badge = Badge.query.get_or_404(badge_id)

    if request.method == "POST":
        user_id = request.form.get("user_id", type=int)
        if not user_id:
            flash("Please select a student.", "warning")
            return redirect(url_for("badges.grant", badge_id=badge.id))

        try:
            _, created = grant_badge(user_id=user_id, badge_id=badge.id, issued_by_id=current_user.id)
            flash("Badge granted." if created else "Student already has that badge.", "success" if created else "info")
        except Exception as e:
            current_app.logger.exception("Grant failed: %s", e)
            flash("Failed to grant badge.", "danger")

        return redirect(url_for("badges.list_badges"))

    # GET: simple page with a select of students
    students = User.query.filter_by(role="student").order_by(User.last_name, User.first_name).all()
    return render_template("badges/grant.html", badge=badge, students=students)


# -----------------------------
# Bulk upload (issuer/admin)
# ZIP with one CSV and optional icons
# -----------------------------
@badges_bp.route("/bulk", methods=["GET", "POST"])
@login_required
def bulk_badges():
    if not _has_role("admin", "issuer"):
        flash("Only staff can bulk upload badges.", "danger")
        return redirect(url_for("badges.list_badges"))

    if request.method == "GET":
        return render_template("badges/bulk.html")

    zip_file = request.files.get("zipfile")
    if not zip_file or not zip_file.filename.lower().endswith(".zip"):
        flash("Please upload a .zip file.", "warning")
        return render_template("badges/bulk.html")

    saved_files: list[str] = []  # web paths to delete on rollback

    try:
        with zipfile.ZipFile(zip_file.stream) as zf:
            # 1) Find CSV
            csv_members = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if not csv_members:
                raise ValueError("No CSV found in the ZIP.")
            if len(csv_members) > 1:
                raise ValueError("Multiple CSV files found; include exactly one.")
            csv_bytes = zf.read(csv_members[0])

            # 2) Build icon index (basename -> member path)
            icon_map: dict[str, str] = {}
            for n in zf.namelist():
                base = os.path.basename(n)
                if base and allowed_image(base):
                    icon_map[base.lower()] = n

            # 3) Parse CSV
            text = io.TextIOWrapper(io.BytesIO(csv_bytes), encoding="utf-8-sig", newline="")
            reader = csv.DictReader(text)
            if not reader.fieldnames:
                raise ValueError("CSV has no header row.")

            cols = {c.strip().lower() for c in reader.fieldnames}
            required = {"name", "points", "description", "icon_name"}
            missing = required - cols
            if missing:
                raise ValueError(f"CSV missing required columns: {', '.join(sorted(missing))}")

            # 4) Validate rows + detect duplicates
            rows: list[tuple[str, int, str | None, str]] = []
            names_lower: set[str] = set()
            errors: list[str] = []

            for i, row in enumerate(reader, start=2):
                name = (row.get("name") or "").strip()
                points_raw = (row.get("points") or "").strip()
                description = (row.get("description") or "").strip() or None
                icon_name = (row.get("icon_name") or "").strip()

                if not name:
                    errors.append(f"Line {i}: 'name' is required.")
                    continue

                key = name.lower()
                if key in names_lower:
                    errors.append(f"Line {i}: duplicate badge name '{name}' in CSV.")
                    continue
                names_lower.add(key)

                try:
                    points = int(points_raw or 0)
                except ValueError:
                    errors.append(f"Line {i}: points '{points_raw}' is not an integer.")
                    continue

                rows.append((name, points, description, icon_name))

            if names_lower:
                existing = (
                    db.session.execute(
                        db.select(Badge.name).where(func.lower(Badge.name).in_(list(names_lower)))
                    )
                    .scalars()
                    .all()
                )
                if existing:
                    errors.append("Already exists in DB: " + ", ".join(sorted(existing)))

            if errors:
                raise ValueError(" • " + " • ".join(errors))

            # 5) Create all (transactional)
            created = 0
            for (name, points, description, icon_name) in rows:
                pil = None
                if icon_name:
                    member = icon_map.get(os.path.basename(icon_name).lower())
                    if member:
                        try:
                            with zf.open(member) as fp:
                                pil = open_image(fp)
                        except Exception:
                            pil = None

                if pil is None:
                    pil = badge_fallback(name)

                icon_path = save_png(square(pil), "icons", name)
                saved_files.append(icon_path)

                db.session.add(
                    Badge(
                        name=name,
                        description=description,
                        icon=icon_path,
                        points=points,
                        created_by_id=current_user.id,
                    )
                )
                created += 1

            db.session.commit()
            flash(f"Bulk upload complete: {created} badges created.", "success")
            return redirect(url_for("badges.list_badges"))

    except Exception as e:
        db.session.rollback()
        for web_path in saved_files:
            remove_web_path(web_path)
        flash(f"Bulk upload failed. No changes were saved. Details: {e}", "danger")
        return render_template("badges/bulk.html")


# -----------------------------
# CSV template for bulk
# -----------------------------
@badges_bp.route("/bulk-template.csv")
@login_required
def bulk_badges_template():
    csv_text = (
        "name,points,description,icon_name\n"
        "First Program,10,Submitted your first working program.,first_program.png\n"
        "Debug Detective,15,Fixed a non-trivial bug using print/logging.,debug.png\n"
        "Team Player,5,Helped a peer solve a problem.,\n"
    )
    return Response(
        csv_text,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=badges_template.csv"},
    )
