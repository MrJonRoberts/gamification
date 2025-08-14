from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from wtforms import StringField, validators
from flask_wtf import FlaskForm
from ...extensions import db
from ...models import User, BadgeGrant, Badge, Award, award_progress, user_total_points

students_bp = Blueprint("students", __name__)

class StudentForm(FlaskForm):
    student_code = StringField("Student Code", [validators.DataRequired(), validators.Length(max=32)])
    email = StringField("Email", [validators.DataRequired(), validators.Email()])
    first_name = StringField("First Name", [validators.DataRequired()])
    last_name = StringField("Last Name", [validators.DataRequired()])

@students_bp.route("/")
@login_required
def list_students():
    q = User.query.filter_by(role="student").order_by(User.last_name, User.first_name).all()
    return render_template("students/list.html", students=q)

@students_bp.route("/create", methods=["GET","POST"])
@login_required
def create_student():
    form = StudentForm()
    if form.validate_on_submit():
        u = User(
            role="student",
            student_code=form.student_code.data.strip(),
            email=form.email.data.lower().strip(),
            first_name=form.first_name.data.strip(),
            last_name=form.last_name.data.strip(),
            registered_method="site"
        )
        u.set_password("ChangeMe123!")  # placeholder
        db.session.add(u)
        db.session.commit()
        flash("Student created.", "success")
        return redirect(url_for("students.list_students"))
    return render_template("students/form.html", form=form)


@students_bp.route("/<int:user_id>")
@login_required
def detail(user_id):
    student = User.query.get_or_404(user_id)
    if student.role != "student":
        flash("Not a student record.", "warning")
        return redirect(url_for("students.list_students"))

    # Most recent first; join to show badge details
    grants = (
        db.session.query(BadgeGrant, Badge)
        .join(Badge, BadgeGrant.badge_id == Badge.id)
        .filter(BadgeGrant.user_id == student.id)
        .order_by(BadgeGrant.issued_at.desc())
        .all()
    )
    total = user_total_points(student.id)
    return render_template("students/detail.html", student=student, grants=grants, total_points=total)

@students_bp.route("/<int:user_id>/awards")
@login_required
def awards_progress(user_id):
    student = User.query.get_or_404(user_id)

    awards = Award.query.order_by(Award.name).all()
    progress_list = []
    for a in awards:
        prog = award_progress(user_id=student.id, award_id=a.id)  # {badge_id: {...}}
        total = len(prog)
        earned = sum(1 for v in prog.values() if v["earned"])
        completed = (total > 0 and earned == total)
        completed_at = max(
            (v["earned_at"] for v in prog.values() if v["earned_at"]),
            default=None
        )
        progress_list.append({
            "award": a,
            "progress": prog,
            "total": total,
            "earned": earned,
            "completed": completed,
            "completed_at": completed_at,
        })

    total_points = user_total_points(student.id)
    return render_template(
        "students/awards.html",
        student=student,
        total_points=total_points,
        progress_list=progress_list
    )

