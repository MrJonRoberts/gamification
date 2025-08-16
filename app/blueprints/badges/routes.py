import hashlib

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from wtforms import StringField, IntegerField, TextAreaField, FileField, validators
from flask_wtf import FlaskForm
from werkzeug.utils import secure_filename
from sqlalchemy import func
from ...extensions import db
from ...models import Badge, User, BadgeGrant, PointLedger
from uuid import uuid4
from PIL import Image, UnidentifiedImageError
import os, io, csv, zipfile

badges_bp = Blueprint("badges", __name__)

ALLOWED_ICON_EXTS = {"png", "jpg", "jpeg", "webp"}

AVATAR_FILES = [
    "dog_1.png",
    "dog_2.png",
    "dog_3.png",
    "dog_4.png",
    "dog_5.png",
]

def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_ICON_EXTS



def _require_admin():
    from flask_login import current_user
    return current_user.is_authenticated and getattr(current_user, "role", "") == "admin"


def _square_150(img: Image.Image) -> Image.Image:
    img = img.convert("RGBA")
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    img = img.crop((left, top, left + side, top + side))
    return img.resize((150, 150), Image.LANCZOS)

def _save_icon_from_pil(name: str, pil_img: Image.Image) -> str:
    base = secure_filename(name).lower() or "badge"
    filename = f"{base}.png"
    save_dir = os.path.join(current_app.root_path, "static", "icons")
    os.makedirs(save_dir, exist_ok=True)
    path = os.path.join(save_dir, filename)
    if os.path.exists(path):
        filename = f"{base}-{uuid4().hex[:6]}.png"
        path = os.path.join(save_dir, filename)
    pil_img.save(path, format="PNG", optimize=True)
    return f"/static/icons/{filename}"

def _load_default_icon() -> Image.Image:
    # Back-compat default (used elsewhere)
    fp = os.path.join(current_app.root_path, "static", "icons", "default.png")
    if os.path.exists(fp):
        img = Image.open(fp); img.load()
        return img
    return Image.new("RGBA", (150, 150), (220, 220, 220, 255))

def _load_avatar_for_name(badge_name: str) -> Image.Image:
    """
    Deterministically pick an avatar based on badge_name.
    If avatars are missing, fall back to _load_default_icon().
    """
    # Filter to ones that actually exist
    root = os.path.join(current_app.root_path, "static", "icons")
    available = [f for f in AVATAR_FILES if os.path.exists(os.path.join(root, f))]
    if not available:
        return _load_default_icon()

    digest = hashlib.md5((badge_name or "").strip().lower().encode("utf-8")).hexdigest()
    idx = int(digest, 16) % len(available)
    fp = os.path.join(root, available[idx])

    try:
        img = Image.open(fp)
        img.load()
        return img
    except Exception:
        # If a specific file is corrupt, try the default icon
        return _load_default_icon()


class BadgeForm(FlaskForm):
    name = StringField("Name", [validators.DataRequired()])
    description = TextAreaField("Description")
    points = IntegerField("Points", [validators.NumberRange(min=0)])
    icon = FileField("Icon (png/jpg/webp)")

@badges_bp.route("/")
@login_required
def list_badges():
    items = Badge.query.order_by(Badge.name).all()
    return render_template("badges/list.html", badges=items)

@badges_bp.route("/create", methods=["GET","POST"])
@login_required
def create_badge():
    form = BadgeForm()
    if form.validate_on_submit():
        name = (form.name.data or "").strip()

        # Enforce unique badge name (case-insensitive)
        exists = db.session.execute(
            db.select(Badge.id).where(func.lower(Badge.name) == name.lower())
        ).first()
        if exists:
            flash("A badge with that name already exists.", "warning")
            return render_template("badges/form.html", form=form)

        icon_path = None

        # Handle optional icon upload with robust checks + resize to 150x150
        file = form.icon.data
        if file and getattr(file, "filename", ""):
            if not allowed_file(file.filename):
                flash("Icon must be a PNG/JPG/JPEG/WEBP file.", "danger")
                return render_template("badges/form.html", form=form)

            try:
                # Open and validate image
                img = Image.open(file.stream)  # Pillow sniffs actual file type
                img.load()  # ensure fully loaded
            except (UnidentifiedImageError, OSError):
                flash("The uploaded file isn’t a valid image.", "danger")
                return render_template("badges/form.html", form=form)

            # Make square (center crop), then resize to 150x150
            try:
                img = img.convert("RGBA")
                w, h = img.size
                side = min(w, h)
                left = (w - side) // 2
                top = (h - side) // 2
                img = img.crop((left, top, left + side, top + side))
                img = img.resize((150, 150), Image.LANCZOS)

                # Build a safe, unique filename (always save as PNG)
                base = secure_filename(name) or "badge"
                filename = f"{base}-{uuid4().hex[:8]}.png"

                save_dir = os.path.join(current_app.root_path, "static", "icons")
                os.makedirs(save_dir, exist_ok=True)
                fp = os.path.join(save_dir, filename)

                # Save optimized PNG
                img.save(fp, format="PNG", optimize=True)
                icon_path = f"/static/icons/{filename}"
            except Exception as e:
                current_app.logger.exception("Failed to process/save icon: %s", e)
                flash("Failed to process the icon image. Please try a different file.", "danger")
                return render_template("badges/form.html", form=form)

        # Create badge
        try:
            b = Badge(
                name=name,
                description=(form.description.data or "").strip() or None,
                icon=icon_path,
                points=form.points.data or 0,
                created_by_id=current_user.id
            )
            db.session.add(b)
            db.session.commit()
            flash("Badge created.", "success")
            return redirect(url_for("badges.list_badges"))
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception("Error creating badge: %s", e)
            # Clean up saved icon if DB commit failed
            if icon_path:
                try:
                    os.remove(os.path.join(current_app.root_path, icon_path.lstrip("/")))
                except OSError:
                    pass
            flash("Could not create the badge due to a server error.", "danger")
            return render_template("badges/form.html", form=form)

    return render_template("badges/form.html", form=form)

@badges_bp.route("/grant/<int:badge_id>", methods=["GET","POST"])
@login_required
def grant(badge_id):
    badge = Badge.query.get_or_404(badge_id)
    if request.method == "POST":
        user_id = int(request.form["user_id"])
        u = User.query.get_or_404(user_id)
        grant = BadgeGrant(user_id=u.id, badge_id=badge.id, issued_by_id=current_user.id)
        db.session.add(grant)
        if badge.points:
            db.session.add(PointLedger(user_id=u.id, delta=badge.points, reason=f"Badge: {badge.name}", source="badge", issued_by_id=current_user.id))
        db.session.commit()
        flash("Badge granted.", "success")
        return redirect(url_for("badges.list_badges"))
    students = User.query.filter_by(role="student").order_by(User.last_name).all()
    return render_template("badges/grant.html", badge=badge, students=students)

@badges_bp.route("/bulk", methods=["GET", "POST"])
@login_required
def bulk_badges():
    """
    Accepts a ZIP with:
      - a CSV (name,points,description,icon_name)
      - icon files referenced by icon_name (any folder structure)
    All or nothing: a failure rolls back DB + removes saved icons.
    """
    if request.method == "GET":
        return render_template("badges/bulk.html")

    # POST:
    file = request.files.get("zipfile")
    if not file or not file.filename.lower().endswith(".zip"):
        flash("Please upload a .zip file.", "warning")
        return render_template("badges/bulk.html")

    saved_files = []  # track saved icon files to delete on rollback
    try:
        with zipfile.ZipFile(file.stream) as zf:
            # Find CSV
            csv_members = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if not csv_members:
                raise ValueError("No CSV found in the ZIP.")
            if len(csv_members) > 1:
                raise ValueError("Multiple CSV files found; include exactly one.")
            csv_name = csv_members[0]
            csv_bytes = zf.read(csv_name)

            # Map icon basenames (case-insensitive) -> ZipInfo
            icon_map = {}
            for n in zf.namelist():
                if allowed_file(n):
                    icon_map[os.path.basename(n).lower()] = n

            # Parse CSV
            text = io.TextIOWrapper(io.BytesIO(csv_bytes), encoding="utf-8-sig", newline="")
            reader = csv.DictReader(text)
            required = {"name", "points", "description", "icon_name"}
            cols = {c.strip().lower() for c in (reader.fieldnames or [])}
            if not required.issubset(cols):
                missing = ", ".join(sorted(required - cols))
                raise ValueError(f"CSV missing required columns: {missing}")

            # Collect rows & validate upfront
            rows = []
            names_lower = set()
            errors = []
            for i, row in enumerate(reader, start=2):  # header is line 1
                name = (row.get("name") or "").strip()
                points_raw = (row.get("points") or "").strip()
                description = (row.get("description") or "").strip() or None
                icon_name = (row.get("icon_name") or "").strip()

                if not name:
                    errors.append(f"Line {i}: 'name' is required.")
                    continue
                # duplicate in CSV?
                key = name.lower()
                if key in names_lower:
                    errors.append(f"Line {i}: duplicate badge name '{name}' in CSV.")
                    continue
                names_lower.add(key)

                # points
                try:
                    points = int(points_raw or 0)
                except ValueError:
                    errors.append(f"Line {i}: points '{points_raw}' is not an integer.")
                    continue

                rows.append((name, points, description, icon_name))

            # duplicate against DB?
            if names_lower:
                exists = (
                    db.session.execute(
                        db.select(Badge.name).where(func.lower(Badge.name).in_(list(names_lower)))
                    ).scalars().all()
                )
                if exists:
                    errors.append("These badge names already exist: " + ", ".join(sorted(exists)))

            if errors:
                raise ValueError(" • " + " • ".join(errors))

            # All clear: build objects but do not commit yet
            created = 0
            default_icon = _load_default_icon()

            for (name, points, description, icon_name) in rows:
                # Load icon from ZIP if provided
                pil = None
                if icon_name:
                    member = icon_map.get(os.path.basename(icon_name).lower())
                    if member:
                        try:
                            with zf.open(member) as fp:
                                img = Image.open(fp);
                                img.load()
                                pil = img
                        except Exception:
                            pil = None  # triggers avatar fallback

                # Fallbacks: missing/blank/invalid -> avatar by name
                if pil is None:
                    pil = _load_avatar_for_name(name)  # NEW

                # Process + save
                icon_processed = _square_150(pil)
                icon_path = _save_icon_from_pil(name, icon_processed)
                saved_files.append(icon_path)

                db.session.add(Badge(
                    name=name,
                    description=description,
                    icon=icon_path,
                    points=points,
                    created_by_id=current_user.id
                ))

            # Commit everything
            db.session.commit()
            flash(f"Bulk upload complete: {created} badges created.", "success")
            return redirect(url_for("badges.list_badges"))

    except Exception as e:
        # Roll back DB
        db.session.rollback()
        # Remove any icons we saved
        for web_path in saved_files:
            try:
                fp = os.path.join(current_app.root_path, web_path.lstrip("/"))
                if os.path.exists(fp):
                    os.remove(fp)
            except OSError:
                pass
        flash(f"Bulk upload failed. No changes were saved. Details: {e}", "danger")
        return render_template("badges/bulk.html")


@badges_bp.route("/bulk-template.csv")
@login_required
def bulk_badges_template():
    csv_text = (
        "name,points,description,icon_name\n"
        "First Program,10,Submitted your first working program.,first_program.png\n"
        "Debug Detective,15,Fixed a non-trivial bug using print/logging.,debug.png\n"
        "Team Player,5,Helped a peer solve a problem.,\n"
    )
    from flask import Response
    return Response(
        csv_text,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=badges_template.csv"},
    )


@badges_bp.route("/edit/<int:badge_id>", methods=["GET", "POST"])
@login_required
def edit_badge(badge_id):
    if not _require_admin():
        flash("Admin access required.", "danger")
        return redirect(url_for("badges.list_badges"))

    badge = Badge.query.get_or_404(badge_id)
    form = BadgeForm(obj=badge)

    if form.validate_on_submit():
        # Enforce unique name (case-insensitive) excluding this badge
        from sqlalchemy import func
        new_name = (form.name.data or "").strip()
        clash = db.session.execute(
            db.select(Badge.id).where(
                func.lower(Badge.name) == new_name.lower(),
                Badge.id != badge.id
            )
        ).first()
        if clash:
            flash("Another badge already uses that name.", "warning")
            return render_template("badges/edit.html", form=form, badge=badge)

        old_icon_path = badge.icon  # web path like /static/icons/xxx.png
        try:
            # Update core fields
            badge.name = new_name
            badge.description = (form.description.data or "").strip() or None
            badge.points = form.points.data or 0

            # Optional: replace the icon if a new file was uploaded
            file = form.icon.data
            if file and getattr(file, "filename", ""):
                # Validate it’s an image
                try:
                    img = Image.open(file.stream); img.load()
                except Exception:
                    flash("Uploaded icon is not a valid image.", "danger")
                    return render_template("badges/edit.html", form=form, badge=badge)

                processed = _square_150(img)
                # Save under (possibly new) name; helpers ensure uniqueness if needed
                new_icon = _save_icon_from_pil(badge.name, processed)
                badge.icon = new_icon

                # Clean up old file if different
                if old_icon_path and old_icon_path != new_icon:
                    try:
                        fp = os.path.join(current_app.root_path, old_icon_path.lstrip("/"))
                        if os.path.exists(fp):
                            os.remove(fp)
                    except OSError:
                        pass

            db.session.commit()
            flash("Badge updated.", "success")
            return redirect(url_for("badges.list_badges"))

        except Exception as e:
            db.session.rollback()
            current_app.logger.exception("Failed to edit badge: %s", e)
            flash("Could not update the badge due to a server error.", "danger")

    return render_template("badges/edit.html", form=form, badge=badge)

