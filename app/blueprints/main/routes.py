from flask import Blueprint, render_template
from flask_login import login_required, current_user
from ...extensions import db
from app.models import User, PointLedger
from sqlalchemy import func

main_bp = Blueprint("main", __name__)

@main_bp.route("/")
@login_required
def index():
    # Simple leaderboard (global)
    rows = db.session.execute(
        db.select(User.id, User.first_name, User.last_name, func.coalesce(func.sum(PointLedger.delta), 0).label("points"))
        .outerjoin(PointLedger, PointLedger.user_id==User.id)
        .where(User.role=="student")
        .group_by(User.id)
        .order_by(func.sum(PointLedger.delta).desc())
        .limit(20)
    ).all()
    return render_template("index.html", leaderboard=rows)


@main_bp.route("/timer")
@login_required
def timer():
    return render_template("timer.html")