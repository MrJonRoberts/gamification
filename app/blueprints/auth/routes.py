from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from wtforms import StringField, PasswordField, SelectField, validators
from flask_wtf import FlaskForm
from ...extensions import db
from ...models import User

auth_bp = Blueprint("auth", __name__)

class LoginForm(FlaskForm):
    email = StringField("Email", [validators.DataRequired(), validators.Email()])
    password = PasswordField("Password", [validators.DataRequired()])

class RegisterForm(FlaskForm):
    student_code = StringField("Student Code")
    email = StringField("Email", [validators.DataRequired(), validators.Email()])
    first_name = StringField("First Name", [validators.DataRequired()])
    last_name = StringField("Last Name", [validators.DataRequired()])
    role = SelectField("Role", choices=[("student","Student"), ("issuer","Issuer"), ("admin","Admin")])
    password = PasswordField("Password", [validators.DataRequired(), validators.Length(min=6)])

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower().strip()).first()
        if user and user.check_password(form.password.data):
            login_user(user)
            return redirect(url_for("main.index"))
        flash("Invalid credentials", "danger")
    return render_template("auth/login.html", form=form)

@auth_bp.route("/register", methods=["GET","POST"])
@login_required
def register():
    if current_user.role not in ("admin", "issuer"):
        flash("Only staff can register users.", "warning")
        return redirect(url_for("main.index"))
    form = RegisterForm()
    if form.validate_on_submit():
        user = User(
            student_code=form.student_code.data or None,
            email=form.email.data.lower().strip(),
            first_name=form.first_name.data.strip(),
            last_name=form.last_name.data.strip(),
            role=form.role.data,
            registered_method="site"
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash("User registered.", "success")
        return redirect(url_for("main.index"))
    return render_template("auth/register.html", form=form)

@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
