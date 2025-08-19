from flask import Blueprint, render_template, jsonify, request, abort
from flask_login import login_required, current_user
from sqlalchemy import func
from app.extensions import db
from app.models import Course, User, Behaviour, SeatingPosition

import logging
log = logging.getLogger(__name__)


seating_bp = Blueprint("seating", __name__, url_prefix="/courses")


def _is_enrolled(course: Course, user: User) -> bool:
    # course.students is a dynamic relationship
    return course.students.filter(User.id == user.id).count() > 0


def _can_manage(course: Course) -> bool:
    # Tighten to your role rules as needed
    return getattr(current_user, "role", "") in {"admin", "issuer"}  # or your own check


@seating_bp.route("/<int:course_id>/seating")
@login_required
def seating_view(course_id):
    course = Course.query.get_or_404(course_id)
    if not _can_manage(course):
        abort(403)

    # roster (Query because lazy="dynamic")
    users = course.students.order_by(User.last_name, User.first_name).all()

    # positions for this course
    pos_map = {
        p.user_id: p
        for p in SeatingPosition.query.filter_by(course_id=course.id).all()
    }

    # behaviour totals per user for this course
    totals = dict(
        db.session.query(Behaviour.user_id, func.coalesce(func.sum(Behaviour.delta), 0))
        .filter(Behaviour.course_id == course.id)
        .group_by(Behaviour.user_id)
        .all()
    )

    return render_template(
        "courses/seating.html",
        course=course,
        users=users,
        pos_map=pos_map,
        totals=totals,
    )


# -------- API: get/save positions --------

@seating_bp.get("/<int:course_id>/api/seating")
@login_required
def api_all_positions(course_id):
    Course.query.get_or_404(course_id)
    rows = SeatingPosition.query.filter_by(course_id=course_id).all()
    return jsonify([{"user_id": r.user_id, "x": r.x, "y": r.y, "locked": r.locked} for r in rows])


@seating_bp.post("/<int:course_id>/api/seating/<int:user_id>")
@seating_bp.post("/<int:course_id>/api/seating/<int:user_id>/")
@login_required
def api_update_position(course_id, user_id):
    # Debug: confirm the route is being hit
    log.debug("api_update_position hit: course=%s user=%s", course_id, user_id)

    course = Course.query.get_or_404(course_id)
    user = User.query.get_or_404(user_id)

    # If you want a 403 instead of 404 when not enrolled:
    if not _can_manage(course) or not _is_enrolled(course, user):
        log.debug("Forbidden: user %s not allowed or not enrolled in course %s", user_id, course_id)
        abort(403)

    data = request.get_json(force=True) or {}
    x = float(data.get("x", 0))
    y = float(data.get("y", 0))
    locked = data.get("locked")

    sp = SeatingPosition.query.filter_by(course_id=course_id, user_id=user_id).first()
    if not sp:
        sp = SeatingPosition(course_id=course_id, user_id=user_id, x=x, y=y)
        db.session.add(sp)
    else:
        if sp.locked and data.get("drag", False):
            return jsonify({"ok": True, "ignored": "locked"})
        sp.x, sp.y = x, y

    if locked is not None:
        sp.locked = bool(locked)

    db.session.commit()
    return jsonify({"ok": True})


@seating_bp.post("/<int:course_id>/api/seating/bulk_lock")
@login_required
def api_bulk_lock(course_id):
    course = Course.query.get_or_404(course_id)
    if not _can_manage(course):
        abort(403)
    data = request.get_json(force=True) or {}
    locked = bool(data.get("locked", True))
    SeatingPosition.query.filter_by(course_id=course_id).update({"locked": locked})
    db.session.commit()
    return jsonify({"ok": True})


# -------- API: +/– behaviour and total for this course --------

@seating_bp.post("/<int:course_id>/api/behaviour/<int:user_id>/adjust")
@login_required
def api_behaviour_adjust(course_id, user_id):
    course = Course.query.get_or_404(course_id)
    user = User.query.get_or_404(user_id)
    if not _can_manage(course) or not _is_enrolled(course, user):
        abort(403)

    data = request.get_json(force=True) or {}
    delta = int(data.get("delta", 0))
    note = (data.get("note") or "").strip()
    if delta == 0:
        return jsonify({"ok": False, "error": "delta required"}), 400

    b = Behaviour(
        user_id=user_id,
        course_id=course_id,
        delta=delta,
        note=note or None,
        created_by_id=current_user.id,
    )
    try:
        db.session.add(b)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(e)}), 500

    total = db.session.query(func.coalesce(func.sum(Behaviour.delta), 0))\
        .filter(Behaviour.user_id == user_id, Behaviour.course_id == course_id)\
        .scalar() or 0

    return jsonify({"ok": True, "total": int(total)})