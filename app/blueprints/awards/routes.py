from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from wtforms import StringField, TextAreaField, IntegerField, SelectMultipleField, widgets, validators
from flask_wtf import FlaskForm
from ...extensions import db
from ...models import Award, AwardBadge, Badge, User, award_progress, PointLedger

awards_bp = Blueprint("awards", __name__)

class MultiCheckboxField(SelectMultipleField):
    widget = widgets.ListWidget(prefix_label=False)
    option_widget = widgets.CheckboxInput()

class AwardForm(FlaskForm):
    name = StringField("Name", [validators.DataRequired()])
    description = TextAreaField("Description")
    points = IntegerField("Extra Points (optional)", [validators.NumberRange(min=0)])
    badges = MultiCheckboxField("Badges", coerce=int)

@awards_bp.route("/")
@login_required
def list_awards():
    items = Award.query.order_by(Award.name).all()
    return render_template("awards/list.html", awards=items)

@awards_bp.route("/create", methods=["GET","POST"])
@login_required
def create_award():
    form = AwardForm()
    form.badges.choices = [(b.id, b.name) for b in Badge.query.order_by(Badge.name).all()]
    if form.validate_on_submit():
        a = Award(name=form.name.data.strip(),
                  description=form.description.data.strip() if form.description.data else None,
                  points=form.points.data or 0, created_by_id=current_user.id)
        db.session.add(a)
        db.session.flush()
        seq = 1
        for bid in form.badges.data:
            db.session.add(AwardBadge(award_id=a.id, badge_id=int(bid), sequence=seq))
            seq += 1
        db.session.commit()
        flash("Award created.", "success")
        return redirect(url_for("awards.list_awards"))
    return render_template("awards/form.html", form=form)

@awards_bp.route("/progress/<int:award_id>/<int:user_id>")
@login_required
def progress(award_id, user_id):
    a = Award.query.get_or_404(award_id)
    u = User.query.get_or_404(user_id)
    progress = award_progress(user_id=u.id, award_id=a.id)
    # Award completion date is max earned_at if all earned
    earned_dates = [v["earned_at"] for v in progress.values() if v["earned_at"]]
    completed = len(progress)>0 and all(v["earned"] for v in progress.values())
    completed_at = max(earned_dates) if completed and earned_dates else None
    return render_template("awards/progress.html", award=a, user=u, progress=progress, completed=completed, completed_at=completed_at)
