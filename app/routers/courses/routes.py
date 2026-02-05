from __future__ import annotations
import io
import pandas as pd
from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db, require_user, AnonymousUser
from app.models import Course, User
from app.templating import render_template
from app.utils import flash

router = APIRouter(prefix="/courses", tags=["courses"])

@router.get("/", response_class=HTMLResponse, name="courses.list_courses")
def list_courses(
    request: Request,
    current_user: User | AnonymousUser = Depends(require_user),
    session: Session = Depends(get_db),
):
    courses = session.query(Course).order_by(Course.year.desc(), Course.semester, Course.name).all()
    return render_template("courses/list.html", {"request": request, "courses": courses, "current_user": current_user})

@router.get("/create", response_class=HTMLResponse, name="courses.create_course")
def create_course_form(
    request: Request,
    current_user: User | AnonymousUser = Depends(require_user),
):
    return render_template("courses/form.html", {"request": request, "current_user": current_user})

@router.post("/create", name="courses.create_course_post")
def create_course_action(
    request: Request,
    name: str = Form(...),
    semester: str = Form(...),
    year: int = Form(...),
    current_user: User | AnonymousUser = Depends(require_user),
    session: Session = Depends(get_db),
):
    c = Course(name=name.strip(), semester=semester, year=year)
    session.add(c)
    session.commit()
    flash(request, "Course created.", "success")
    return RedirectResponse("/courses/", status_code=303)

@router.get("/{course_id}/enroll", response_class=HTMLResponse, name="courses.enroll")
def enroll_form(
    course_id: int,
    request: Request,
    current_user: User | AnonymousUser = Depends(require_user),
    session: Session = Depends(get_db),
):
    course = session.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    students = session.query(User).filter_by(role="student").order_by(User.last_name, User.first_name).all()
    enrolled_students = sorted(course.students, key=lambda s: (s.last_name.lower(), s.first_name.lower()))

    return render_template(
        "courses/enroll.html",
        {
            "request": request,
            "course": course,
            "students": students,
            "enrolled_students": enrolled_students,
            "current_user": current_user,
        },
    )

@router.post("/{course_id}/enroll", name="courses.enroll_post")
async def enroll_action(
    course_id: int,
    request: Request,
    action: str = Form("single"),
    # Single
    user_id: int = Form(None),
    # Create
    first_name: str = Form(None),
    last_name: str = Form(None),
    email: str = Form(None),
    student_code: str = Form(None),
    # Bulk
    file: UploadFile = File(None),
    current_user: User | AnonymousUser = Depends(require_user),
    session: Session = Depends(get_db),
):
    course = session.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    if action == "single":
        if user_id is None:
            flash(request, "Please choose a student.", "warning")
            return RedirectResponse(f"/courses/{course_id}/enroll", status_code=303)

        u = session.get(User, user_id)
        if not u:
            raise HTTPException(status_code=404, detail="User not found")

        if u not in course.students:
            course.students.append(u)
            session.commit()
            flash(request, f"Enrolled {u.full_name}.", "success")
        else:
            flash(request, f"{u.full_name} is already enrolled.", "info")
        return RedirectResponse(f"/courses/{course_id}/enroll", status_code=303)

    if action == "create":
        if not (first_name and last_name and email):
            flash(request, "First name, last name, and email are required to create a student.", "danger")
            return RedirectResponse(f"/courses/{course_id}/enroll", status_code=303)

        existing = session.query(User).filter_by(email=email.strip().lower()).first()
        if existing:
            u = existing
        else:
            u = User(
                student_code=student_code.strip() if student_code else None,
                email=email.strip().lower(),
                first_name=first_name.strip(),
                last_name=last_name.strip(),
                role="student",
                registered_method="site",
            )
            u.set_password("ChangeMe123!")
            session.add(u)
            session.flush()

        if u not in course.students:
            course.students.append(u)
        session.commit()
        flash(request, f"Student {'created and ' if not existing else ''}enrolled: {u.full_name}.", "success")
        return RedirectResponse(f"/courses/{course_id}/enroll", status_code=303)

    if action == "bulk":
        if not file or not file.filename:
            flash(request, "Please choose a CSV or XLSX file.", "warning")
            return RedirectResponse(f"/courses/{course_id}/enroll", status_code=303)

        fname = file.filename.lower()
        try:
            contents = await file.read()
            if fname.endswith(".csv"):
                df = pd.read_csv(io.BytesIO(contents))
            elif fname.endswith(".xlsx") or fname.endswith(".xls"):
                df = pd.read_excel(io.BytesIO(contents))
            else:
                flash(request, "Unsupported file type. Please upload .csv or .xlsx", "danger")
                return RedirectResponse(f"/courses/{course_id}/enroll", status_code=303)
        except Exception as e:
            flash(request, f"Could not read file: {e}", "danger")
            return RedirectResponse(f"/courses/{course_id}/enroll", status_code=303)

        df.columns = [c.strip().lower() for c in df.columns]
        required = {"email", "first_name", "last_name"}
        missing = required - set(df.columns)
        if missing:
            flash(request, f"Missing required columns: {', '.join(sorted(missing))}", "danger")
            return RedirectResponse(f"/courses/{course_id}/enroll", status_code=303)

        created, enrolled, skipped = 0, 0, 0
        for _, row in df.iterrows():
            u_email = str(row.get("email", "")).strip().lower()
            u_first = str(row.get("first_name", "")).strip()
            u_last  = str(row.get("last_name", "")).strip()
            u_code  = str(row.get("student_code", "")).strip() or None

            if not (u_email and u_first and u_last):
                skipped += 1
                continue

            u = session.query(User).filter_by(email=u_email).first()
            if not u:
                u = User(
                    student_code=u_code,
                    email=u_email,
                    first_name=u_first,
                    last_name=u_last,
                    role="student",
                    registered_method="bulk",
                )
                u.set_password("ChangeMe123!")
                session.add(u)
                session.flush()
                created += 1

            if u not in course.students:
                course.students.append(u)
                enrolled += 1

        session.commit()
        msg = f"Bulk upload complete: {created} created, {enrolled} enrolled, {skipped} skipped (missing fields)."
        flash(request, msg, "success")
        return RedirectResponse(f"/courses/{course_id}/enroll", status_code=303)

    flash(request, "Unknown action.", "danger")
    return RedirectResponse(f"/courses/{course_id}/enroll", status_code=303)

@router.get("/enroll_template.csv", name="courses.enroll_template")
def enroll_template(current_user: User | AnonymousUser = Depends(require_user)):
    csv_text = "first_name,last_name,email,student_code\nKai,Nguyen,kai@example.com,STU100\nMia,Singh,mia@example.com,STU101\n"
    return Response(
        csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=enroll_template.csv"},
    )

@router.get("/{course_id}/students", response_class=HTMLResponse, name="courses.students_in_course")
def students_in_course(
    course_id: int,
    request: Request,
    current_user: User | AnonymousUser = Depends(require_user),
    session: Session = Depends(get_db),
):
    course = session.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    students = sorted(course.students, key=lambda s: (s.last_name.lower(), s.first_name.lower()))
    return render_template("courses/students.html", {"request": request, "course": course, "students": students, "current_user": current_user})
