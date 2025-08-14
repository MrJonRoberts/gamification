from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from wtforms import IntegerField, StringField, SelectField, validators
from flask_wtf import FlaskForm
from ...extensions import db
from ...models import User, PointLedger, Course

points_bp = Blueprint("points", __name__)

class PointsForm(FlaskForm):
    user_id = SelectField("Student", coerce=int)
    delta = IntegerField("Points (+/-)", [validators.DataRequired()])
    reason = StringField("Reason", [validators.DataRequired()])
    course_id = SelectField("Course (optional)", coerce=int, choices=[(0, "—")])

@points_bp.route("/adjust", methods=["GET","POST"])
@login_required
def adjust():
    form = PointsForm()
    form.user_id.choices = [(u.id, f"{u.last_name}, {u.first_name}") for u in User.query.filter_by(role="student").order_by(User.last_name).all()]
    courses = Course.query.order_by(Course.year.desc()).all()
    form.course_id.choices = [(0, "—")] + [(c.id, f"{c.name} {c.semester}{c.year}") for c in courses]
    if form.validate_on_submit():
        course_id = None if form.course_id.data == 0 else form.course_id.data
        entry = PointLedger(user_id=form.user_id.data, delta=form.delta.data, reason=form.reason.data.strip(),
                            source="manual", course_id=course_id, issued_by_id=current_user.id)
        db.session.add(entry)
        db.session.commit()
        flash("Points updated.", "success")
        return redirect(url_for("main.index"))
    return render_template("points/adjust.html", form=form)
