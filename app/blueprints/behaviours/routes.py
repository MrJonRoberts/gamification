from flask import Blueprint, request, jsonify, current_app, render_template
from flask_login import login_required, current_user
from ...extensions import db
from app.models import Behaviour, PointLedger, User, Course
from sqlalchemy import func

behaviours_bp = Blueprint("behaviours", __name__)

def _staff_only() -> bool:
    return current_user.is_authenticated and getattr(current_user, "role", "") in {"admin", "issuer"}

@behaviours_bp.post("/add")
@login_required
def add_behaviour():
    if not _staff_only():
        return jsonify({"ok": False, "error": "Permission denied"}), 403

    try:
        user_id = int(request.form.get("user_id", 0))
        course_id_raw = request.form.get("course_id")
        course_id = int(course_id_raw) if course_id_raw and str(course_id_raw).isdigit() else None
        delta = int(request.form.get("delta", 0))
        note = (request.form.get("note") or "").strip()
    except Exception:
        return jsonify({"ok": False, "error": "Invalid payload"}), 400

    if not user_id or delta == 0:
        return jsonify({"ok": False, "error": "Student and non-zero points are required"}), 400

    user = User.query.get(user_id)
    if not user:
        return jsonify({"ok": False, "error": "Student not found"}), 404
    course = Course.query.get(course_id) if course_id else None

    try:
        # No 'begin()' — just add and commit on the request session
        b = Behaviour(
            user_id=user.id,
            course_id=course.id if course else None,
            delta=delta,
            note=note or None,
            created_by_id=current_user.id,
        )
        db.session.add(b)

        db.session.add(PointLedger(
            user_id=user.id,
            delta=delta,
            reason=f"Behaviour: {note[:120]}" if note else "Behaviour",
            source="behaviour",
            issued_by_id=current_user.id,
        ))

        db.session.commit()
        return jsonify({"ok": True})
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Behaviour add failed: %s", e)
        return jsonify({"ok": False, "error": "Server error"}), 500


@behaviours_bp.get("/list")
@login_required
def list_behaviours():
    user_id = request.args.get("user_id", type=int)
    if not user_id:
        return "<div class='text-danger small'>Missing user_id</div>", 400

    course_id = request.args.get("course_id", type=int)

    # Base query (no limits) used for totals
    base = db.session.query(Behaviour).filter(Behaviour.user_id == user_id)
    if course_id:
        base = base.filter(Behaviour.course_id == course_id)

    # Rows to display (latest 50)
    behaviours = (
        base.order_by(Behaviour.created_at.desc(), Behaviour.id.desc())
            .limit(50)
            .all()
    )

    # Totals
    total_all = (
        db.session.query(func.coalesce(func.sum(Behaviour.delta), 0))
        .filter(Behaviour.user_id == user_id)
        .filter(Behaviour.course_id == course_id) if course_id
        else db.session.query(func.coalesce(func.sum(Behaviour.delta), 0)).filter(Behaviour.user_id == user_id)
    ).scalar() or 0

    total_shown = sum((b.delta or 0) for b in behaviours)

    return render_template(
        "behaviours/_list.html",
        behaviours=behaviours,
        total_all=int(total_all),
        total_shown=int(total_shown),
    )