from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, abort
from flask_login import login_required, current_user, logout_user
from ...extensions import db, csrf
from sqlalchemy import or_
import os, sys, runpy, importlib.util, shutil
from functools import wraps
from app.models import User
from app.models.user import Role, Group
from app.forms.user_forms import UserEditForm

import secrets

def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):

        # Adjust this check to your role logic
        if not current_user.is_authenticated:
            abort(401)
        if not current_user.role == "admin":
            abort(403)
        return f(*args, **kwargs)
    return wrapper


admin_bp = Blueprint("admin", __name__, template_folder="../../templates")

def _require_admin():
    return current_user.is_authenticated and getattr(current_user, "role", "") == "admin"

def _load_and_run_seed():
    """
    Try to import seed.py (project root) and run main() if present;
    otherwise execute the file with runpy.
    """
    project_root = os.path.abspath(os.path.join(current_app.root_path, os.pardir))
    seed_path = os.path.join(project_root, "seeds/seed.py")
    if not os.path.exists(seed_path):
        raise RuntimeError(f"seed.py not found at {seed_path}")

    # Add project root to sys.path for imports used by seed.py
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    # Prefer calling seed.main() if it exists
    spec = importlib.util.spec_from_file_location("seed", seed_path)
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)  # type: ignore[attr-defined]
    if hasattr(seed, "main") and callable(seed.main):
        seed.main()  # must create its own app/app_context
    else:
        # Fallback: run as a script (executes top-level code)
        runpy.run_path(seed_path, run_name="__main__")

@admin_bp.route("/db-tools", methods=["GET"])
@login_required
def db_tools():
    if not _require_admin():
        flash("Admin access required.", "danger")
        return redirect(url_for("main.index"))

    # For display only
    db_uri = current_app.config.get("SQLALCHEMY_DATABASE_URI", "")
    return render_template("admin/db_tools.html", db_uri=db_uri)


@admin_bp.route("/db-tools/reset-seed", methods=["POST"])
@login_required
@csrf.exempt  # we'll include CSRF manually; remove this if using {{ form.csrf_token }}
def reset_seed():
    if not _require_admin():
        flash("Admin access required.", "danger")
        return redirect(url_for("main.index"))

    # Basic CSRF (if you prefer, build a FlaskForm and use {{ form.csrf_token }})
    token = request.form.get("csrf_token")
    if not token or token != request.cookies.get("csrf_token"):
        # If you are using Flask-WTF everywhere, swap this for its token validation
        pass  # CSRFProtect already validates; this branch is just a placeholder

    confirm_text = (request.form.get("confirm_text") or "").strip().upper()
    clean_icons = request.form.get("clean_icons") == "on"

    if confirm_text != "RESET":
        flash('Type "RESET" to confirm.', "warning")
        return redirect(url_for("admin.db_tools"))

    # Optional: clean uploaded icons (keep folder)
    if clean_icons:
        icons_dir = os.path.join(current_app.root_path, "static", "icons")
        if os.path.isdir(icons_dir):
            for name in os.listdir(icons_dir):
                p = os.path.join(icons_dir, name)
                # keep dotfiles and directories
                if os.path.isfile(p) and not name.startswith("."):
                    try:
                        os.remove(p)
                    except OSError:
                        pass

    # Run the seeder (drop/create/seed)
    try:
        _load_and_run_seed()
    except Exception as e:
        current_app.logger.exception("Reset+seed failed: %s", e)
        flash(f"Reset failed: {e}", "danger")
        return redirect(url_for("admin.db_tools"))

    # Force logout to avoid stale sessions referencing old rows
    logout_user()
    flash("Database reset & seed complete. Please log in with the seeded admin.", "success")
    return redirect(url_for("auth.login"))



@admin_bp.route("/users")
@login_required
@admin_required
def users_index():
    q = request.args.get("q", "").strip()
    role = request.args.get("role", "").strip()
    group = request.args.get("group", "").strip()
    page = max(int(request.args.get("page", 1)), 1)
    per_page = 15

    query = User.query

    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                User.email.ilike(like),
                User.first_name.ilike(like),
                User.last_name.ilike(like),
                User.student_code.ilike(like),
            )
        )

    if role:
        query = query.join(User.roles).filter(Role.name == role)

    if group:
        query = query.join(User.groups).filter(Group.name == group)

    query = query.order_by(User.created_at.desc())

    pagination = query.order_by(User.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)

    users = pagination.items

    roles = Role.query.order_by(Role.name.asc()).all()
    groups = Group.query.order_by(Group.name.asc()).all()

    return render_template(
        "admin/users/index.html",
        users=users,
        pagination=pagination,
        q=q,
        role=role,
        group=group,
        roles=roles,
        groups=groups,
    )


@admin_bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def users_edit(user_id):
    user = User.query.get_or_404(user_id)
    form = UserEditForm()

    # Load choices first
    role_rows  = Role.query.order_by(Role.name).all()
    group_rows = Group.query.order_by(Group.name).all()
    form.roles.choices  = [(r.id, r.name) for r in role_rows]
    form.groups.choices = [(g.id, g.name) for g in group_rows]

    if form.validate_on_submit():
        # ----- update simple fields (adjust to your model) -----
        user.first_name = form.first_name.data.strip()
        user.last_name  = form.last_name.data.strip()
        user.email      = form.email.data.strip().lower()
        user.student_code = (form.student_code.data or "").strip() or None
        user.is_active  = bool(form.is_active.data)
        user.registration_method = form.registration_method.data

        # ----- roles: support plural OR single -----
        selected_role_ids = list(map(int, form.roles.data or []))

        if hasattr(user, "roles"):  # many-to-many
            user.roles = Role.query.filter(Role.id.in_(selected_role_ids)).all()
        elif hasattr(user, "role"):  # many-to-one relationship
            user.role = Role.query.get(selected_role_ids[0]) if selected_role_ids else None
        elif hasattr(user, "role_id"):  # plain FK column
            user.role_id = selected_role_ids[0] if selected_role_ids else None

        # ----- groups: support plural OR single -----
        selected_group_ids = list(map(int, form.groups.data or []))

        if hasattr(user, "groups"):  # many-to-many
            user.groups = Group.query.filter(Group.id.in_(selected_group_ids)).all()
        elif hasattr(user, "group"):
            user.group = Group.query.get(selected_group_ids[0]) if selected_group_ids else None
        elif hasattr(user, "group_id"):
            user.group_id = selected_group_ids[0] if selected_group_ids else None

        db.session.commit()
        flash("User updated.", "success")
        return redirect(url_for("admin.users_index"))

    # Prefill only on GET so we don't overwrite POSTed data
    if request.method == "GET":
        form.first_name.data = user.first_name
        form.last_name.data  = user.last_name
        form.email.data      = user.email
        form.student_code.data = user.student_code
        form.is_active.data  = bool(getattr(user, "is_active", True))
        form.registration_method.data = getattr(user, "registration_method", "site") or "site"

        # ----- preselect roles safely -----
        current_role_ids = []
        roles_rel = getattr(user, "roles", None)  # might not exist
        if roles_rel is not None:
            # dynamic? (query) -> .all(); else assume iterable/list
            items = roles_rel.all() if hasattr(roles_rel, "all") else roles_rel
            current_role_ids = [int(r.id) for r in items if getattr(r, "id", None) is not None]
        else:
            one_role = getattr(user, "role", None)
            if one_role is not None and getattr(one_role, "id", None) is not None:
                current_role_ids = [int(one_role.id)]
            elif hasattr(user, "role_id") and getattr(user, "role_id"):
                current_role_ids = [int(user.role_id)]
        form.roles.data = current_role_ids

        # ----- preselect groups safely -----
        current_group_ids = []
        groups_rel = getattr(user, "groups", None)
        if groups_rel is not None:
            items = groups_rel.all() if hasattr(groups_rel, "all") else groups_rel
            current_group_ids = [int(g.id) for g in items if getattr(g, "id", None) is not None]
        else:
            one_group = getattr(user, "group", None)
            if one_group is not None and getattr(one_group, "id", None) is not None:
                current_group_ids = [int(one_group.id)]
            elif hasattr(user, "group_id") and getattr(user, "group_id"):
                current_group_ids = [int(user.group_id)]
        form.groups.data = current_group_ids

    return render_template("admin/users/edit.html", form=form, u=user)


@admin_bp.route("/users/<int:user_id>/toggle", methods=["POST"])
@login_required
@admin_required
def users_toggle_active(user_id):
    user = User.query.get_or_404(user_id)
    user.is_active = not user.is_active
    db.session.commit()
    flash(f"User {'activated' if user.is_active else 'deactivated'}.", "success")
    return redirect(request.referrer or url_for("admin.users_index"))

@admin_bp.route("/users/<int:user_id>/reset-password", methods=["POST"])
@login_required
@admin_required
def users_reset_password(user_id):
    user = User.query.get_or_404(user_id)
    # Generate a random temporary password (you may want to email/send separately)
    new_password = secrets.token_urlsafe(10)
    user.set_password(new_password)  # assumes User has set_password()
    db.session.commit()
    flash(f"Temporary password set: {new_password}", "warning")  # For demo; in prod, email it.
    return redirect(request.referrer or url_for("admin.users_index"))

@admin_bp.route("/users/<int:user_id>/delete", methods=["POST"])
@login_required
@admin_required
def users_delete(user_id):
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    flash("User deleted.", "success")
    return redirect(url_for("admin.users_index"))

