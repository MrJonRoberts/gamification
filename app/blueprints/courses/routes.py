from flask import Blueprint, render_template, request, redirect, url_for, flash, Response
from flask_login import login_required
from wtforms import StringField, IntegerField, SelectField, validators
from flask_wtf import FlaskForm
from ...extensions import db
from ...models import Course, User
import io
import pandas as pd

courses_bp = Blueprint("courses", __name__)

class CourseForm(FlaskForm):
    name = StringField("Course Name", [validators.DataRequired()])
    semester = SelectField("Semester", choices=[("S1","S1"), ("S2","S2")])
    year = IntegerField("Year", [validators.DataRequired()])

@courses_bp.route("/")
@login_required
def list_courses():
    courses = Course.query.order_by(Course.year.desc(), Course.semester, Course.name).all()
    return render_template("courses/list.html", courses=courses)

@courses_bp.route("/create", methods=["GET","POST"])
@login_required
def create_course():
    form = CourseForm()
    if form.validate_on_submit():
        c = Course(name=form.name.data.strip(), semester=form.semester.data, year=form.year.data)
        db.session.add(c)
        db.session.commit()
        flash("Course created.", "success")
        return redirect(url_for("courses.list_courses"))
    return render_template("courses/form.html", form=form)

@courses_bp.route("/<int:course_id>/enroll", methods=["GET","POST"])
@login_required
def enroll(course_id):
    course = Course.query.get_or_404(course_id)

    if request.method == "POST":
        action = request.form.get("action", "single")

        # 1) Enrol existing student from dropdown
        if action == "single":
            try:
                user_id = int(request.form["user_id"])
            except (KeyError, ValueError):
                flash("Please choose a student.", "warning")
                return redirect(url_for("courses.enroll", course_id=course.id))

            u = User.query.get_or_404(user_id)
            if u not in course.students:
                course.students.append(u)
                db.session.commit()
                flash(f"Enrolled {u.full_name}.", "success")
            else:
                flash(f"{u.full_name} is already enrolled.", "info")
            return redirect(url_for("courses.enroll", course_id=course.id))

        # 2) Create a new student and enrol
        if action == "create":
            first = request.form.get("first_name", "").strip()
            last = request.form.get("last_name", "").strip()
            email = request.form.get("email", "").strip().lower()
            code = request.form.get("student_code", "").strip() or None

            if not (first and last and email):
                flash("First name, last name, and email are required to create a student.", "danger")
                return redirect(url_for("courses.enroll", course_id=course.id))

            existing = User.query.filter_by(email=email).first()
            if existing:
                u = existing
                # If they already exist but aren’t a student, we’ll still allow enrol; role won’t change.
            else:
                u = User(
                    student_code=code,
                    email=email,
                    first_name=first,
                    last_name=last,
                    role="student",
                    registered_method="site",
                )
                u.set_password("ChangeMe123!")
                db.session.add(u)
                db.session.flush()

            if u not in course.students:
                course.students.append(u)
            db.session.commit()
            flash(f"Student {'created and ' if not existing else ''}enrolled: {u.full_name}.", "success")
            return redirect(url_for("courses.enroll", course_id=course.id))

        # 3) Bulk upload via CSV/XLSX
        if action == "bulk":
            file = request.files.get("file")
            if not file or file.filename == "":
                flash("Please choose a CSV or XLSX file.", "warning")
                return redirect(url_for("courses.enroll", course_id=course.id))

            fname = file.filename.lower()
            try:
                if fname.endswith(".csv"):
                    df = pd.read_csv(file)
                elif fname.endswith(".xlsx") or fname.endswith(".xls"):
                    df = pd.read_excel(file)
                else:
                    flash("Unsupported file type. Please upload .csv or .xlsx", "danger")
                    return redirect(url_for("courses.enroll", course_id=course.id))
            except Exception as e:
                flash(f"Could not read file: {e}", "danger")
                return redirect(url_for("courses.enroll", course_id=course.id))

            # Normalise columns
            df.columns = [c.strip().lower() for c in df.columns]
            required = {"email", "first_name", "last_name"}
            missing = required - set(df.columns)
            if missing:
                flash(f"Missing required columns: {', '.join(sorted(missing))}", "danger")
                return redirect(url_for("courses.enroll", course_id=course.id))

            # Optional column: student_code
            created, enrolled, skipped = 0, 0, 0
            for _, row in df.iterrows():
                email = str(row.get("email", "")).strip().lower()
                first = str(row.get("first_name", "")).strip()
                last  = str(row.get("last_name", "")).strip()
                code  = str(row.get("student_code", "")).strip() or None

                if not (email and first and last):
                    skipped += 1
                    continue

                u = User.query.filter_by(email=email).first()
                if not u:
                    u = User(
                        student_code=code,
                        email=email,
                        first_name=first,
                        last_name=last,
                        role="student",
                        registered_method="bulk",
                    )
                    u.set_password("ChangeMe123!")
                    db.session.add(u)
                    db.session.flush()
                    created += 1

                if u not in course.students:
                    course.students.append(u)
                    enrolled += 1

            db.session.commit()
            msg = f"Bulk upload complete: {created} created, {enrolled} enrolled, {skipped} skipped (missing fields)."
            flash(msg, "success")
            return redirect(url_for("courses.enroll", course_id=course.id))

        flash("Unknown action.", "danger")
        return redirect(url_for("courses.enroll", course_id=course.id))

    # GET
    students = User.query.filter_by(role="student").order_by(User.last_name, User.first_name).all()
    enrolled_students = course.students.order_by(User.last_name, User.first_name).all()
    return render_template("courses/enroll.html", course=course, students=students, enrolled_students=enrolled_students)

@courses_bp.route("/enroll_template.csv")
@login_required
def enroll_template():
    # Dynamic CSV template download
    csv_text = "first_name,last_name,email,student_code\nKai,Nguyen,kai@example.com,STU100\nMia,Singh,mia@example.com,STU101\n"
    return Response(
        csv_text,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=enroll_template.csv"},
    )

@courses_bp.route("/<int:course_id>/students")
@login_required
def students_in_course(course_id):
    course = Course.query.get_or_404(course_id)
    # course.students is a dynamic relationship; ensure deterministic order
    students = sorted(course.students, key=lambda s: (s.last_name.lower(), s.first_name.lower()))
    return render_template("courses/students.html", course=course, students=students)

