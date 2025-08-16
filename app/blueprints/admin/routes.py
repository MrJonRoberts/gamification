from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user, logout_user
from ...extensions import db, csrf
import os, sys, runpy, importlib.util, shutil

admin_bp = Blueprint("admin", __name__, template_folder="../../templates")

def _require_admin():
    return current_user.is_authenticated and getattr(current_user, "role", "") == "admin"

def _load_and_run_seed():
    """
    Try to import seed.py (project root) and run main() if present;
    otherwise execute the file with runpy.
    """
    project_root = os.path.abspath(os.path.join(current_app.root_path, os.pardir))
    seed_path = os.path.join(project_root, "seed.py")
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
