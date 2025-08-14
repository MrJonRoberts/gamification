from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from wtforms import StringField, IntegerField, TextAreaField, FileField, validators
from flask_wtf import FlaskForm
from werkzeug.utils import secure_filename
from ...extensions import db
from ...models import Badge, BadgeGrant, User, PointLedger
import os

badges_bp = Blueprint("badges", __name__)

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
        icon_path = None
        if form.icon.data:
            filename = secure_filename(form.icon.data.filename)
            save_dir = os.path.join("app","static","icons")
            os.makedirs(save_dir, exist_ok=True)
            fp = os.path.join(save_dir, filename)
            form.icon.data.save(fp)
            icon_path = f"/static/icons/{filename}"
        b = Badge(name=form.name.data.strip(),
                  description=form.description.data.strip() if form.description.data else None,
                  icon=icon_path, points=form.points.data or 0, created_by_id=current_user.id)
        db.session.add(b)
        db.session.commit()
        flash("Badge created.", "success")
        return redirect(url_for("badges.list_badges"))
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
