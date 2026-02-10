from __future__ import annotations
import io
import os
from datetime import datetime, timezone
from typing import Optional

import httpx
import pandas as pd
from openpyxl import load_workbook
from PIL import Image
from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db, require_user, AnonymousUser
from app.models import Course, User, Role, House, Homeroom, Group
from app.templating import render_template
from app.utils import flash

router = APIRouter(prefix="/courses", tags=["courses"])

TASS_IMAGE_URL = "https://alpha.tas.qld.edu.au/kiosk/inline-file.cfm"
IMAGE_PROXY_TIMEOUT_SECONDS = 10.0
IMAGE_PROXY_MAX_BYTES = 5 * 1024 * 1024


def _split_student_name(name_str: str) -> tuple[str, str]:
    """
    Parse TASS name format: "Lastname, Firstname Middlename".
    Middle names are intentionally dropped.
    """
    value = (name_str or "").strip()
    if not value:
        return "", ""

    if "," in value:
        last, first_part = value.split(",", 1)
        first_tokens = first_part.strip().split()
        first_name = first_tokens[0] if first_tokens else ""
        return first_name, last.strip()

    tokens = value.split()
    if len(tokens) >= 2:
        return tokens[0], " ".join(tokens[1:])
    return tokens[0], ""


def _sanitize_student_code(student_code: str) -> str:
    return "".join(ch for ch in (student_code or "") if ch.isalnum())


def _extract_tass_row_images(content: bytes) -> dict[int, bytes]:
    """
    Extract embedded worksheet images by Excel row index (1-based).
    Only column A images are considered (new TASS export format).
    """
    workbook = load_workbook(io.BytesIO(content), data_only=True)
    sheet = workbook.active

    row_to_image: dict[int, bytes] = {}
    for image in getattr(sheet, "_images", []):
        anchor_from = getattr(getattr(image, "anchor", None), "_from", None)
        if anchor_from is None:
            continue

        # openpyxl anchor coordinates are 0-based.
        if int(anchor_from.col) != 0:
            continue

        row_index = int(anchor_from.row) + 1

        data = None
        try:
            data = image._data()
        except Exception:
            image_ref = getattr(image, "ref", None)
            if hasattr(image_ref, "read"):
                try:
                    data = image_ref.read()
                except Exception:
                    data = None

        if data:
            row_to_image[row_index] = data

    return row_to_image


def _save_student_photo(student_code: str, image_bytes: bytes) -> str | None:
    """Save student image as JPEG into static/img/stds using sanitized student code."""
    safe_code = _sanitize_student_code(student_code)
    if not safe_code or not image_bytes:
        return None

    images_dir = os.path.join("app", "static", "img", "stds")
    os.makedirs(images_dir, exist_ok=True)
    image_path = os.path.join(images_dir, f"{safe_code}.jpg")

    try:
        with Image.open(io.BytesIO(image_bytes)) as raw:
            image = raw.convert("RGB")
            image.save(image_path, format="JPEG", quality=90)
    except Exception:
        return None

    return image_path

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
async def create_course_action(
    request: Request,
    name: Optional[str] = Form(None),
    semester: str = Form("S1"),
    year: Optional[int] = Form(None),
    file: UploadFile = File(None),
    current_user: User | AnonymousUser = Depends(require_user),
    session: Session = Depends(get_db),
):
    course_name = (name or "").strip()
    if not year:
        year = datetime.now(timezone.utc).year

    students_to_enroll = []
    student_codes_for_images: list[str] = []
    saved_embedded_images = 0

    if file and file.filename:
        if not file.filename.lower().endswith(".xlsx"):
            flash(request, "Please upload an XLSX file for TASS format.", "warning")
            return RedirectResponse("/courses/create", status_code=303)

        try:
            content = await file.read()
            df_full = pd.read_excel(io.BytesIO(content), header=None)

            # Detect TASS format
            is_tass = False
            if len(df_full) > 2:
                row0 = str(df_full.iloc[0, 0]).upper()
                if "TRINITY ANGLICAN SCHOOL" in row0 and "CLASS LISTING" in row0:
                    is_tass = True

            if is_tass:
                row_images = _extract_tass_row_images(content)

                # Course Name from Row 3 (index 2) if not provided
                if not course_name:
                    course_name = str(df_full.iloc[2, 0]).strip()

                # Headers are in Row 2 (index 1)
                df = pd.read_excel(io.BytesIO(content), header=1)
                # Skip the class info row which is now the first row of data
                df = df.iloc[1:].reset_index(drop=True)
                # Drop summary rows
                df = df[df['Code'].notna()]
                df = df[~df['Code'].astype(str).str.contains("Students in Class", na=False)]

                student_role = session.query(Role).filter_by(name='student').first()

                for row_offset, (_, row) in enumerate(df.iterrows(), start=4):
                    u_email = str(row.get('Email', '')).strip().lower()
                    if not u_email or u_email == 'nan':
                        continue

                    u_code = str(row.get('Code', '')).strip()
                    if u_code.endswith('.0'): # handle float conversion from excel
                        u_code = u_code[:-2]

                    u = session.query(User).filter_by(email=u_email).first()
                    if not u:
                        u = User(
                            email=u_email,
                            student_code=u_code,
                            registered_method='bulk-tass'
                        )
                        u.set_password(u_code) # Default password is their code
                        if student_role:
                            u.roles.append(student_role)
                        session.add(u)
                    else:
                        # Update student code if missing
                        if not u.student_code:
                            u.student_code = u_code

                    # Split Name: "Lastname, Firstname Middlename" and drop middle names.
                    parsed_first, parsed_last = _split_student_name(str(row.get('Student Name', '')))
                    if parsed_first:
                        u.first_name = parsed_first
                    if parsed_last:
                        u.last_name = parsed_last

                    # House
                    house_val = row.get('House')
                    if house_val and not pd.isna(house_val):
                        h_name = str(house_val).strip()
                        h = session.query(House).filter_by(name=h_name).first()
                        if not h:
                            h = House(name=h_name)
                            session.add(h)
                            session.flush()
                        u.house = h

                    # PC/Tutor Group -> Homeroom
                    pc_val = row.get('PC/Tutor Group')
                    if pc_val and not pd.isna(pc_val):
                        hr_name = str(pc_val).strip()
                        hr = session.query(Homeroom).filter_by(name=hr_name).first()
                        if not hr:
                            hr = Homeroom(name=hr_name)
                            session.add(hr)
                            session.flush()
                        u.homeroom = hr

                    # Year Group (as Group for compatibility)
                    yr_val = row.get('Year')
                    if yr_val and not pd.isna(yr_val):
                        yg_name = f"Year {int(float(yr_val))}"
                        yg = session.query(Group).filter_by(name=yg_name).first()
                        if not yg:
                            yg = Group(name=yg_name)
                            session.add(yg)
                            session.flush()
                        if yg not in u.groups:
                            u.groups.append(yg)

                    students_to_enroll.append(u)
                    if u_code:
                        student_codes_for_images.append(u_code)

                        # First student row is Excel row 4 in the TASS export format.
                        excel_row = row_offset
                        photo_bytes = row_images.get(excel_row)
                        if photo_bytes and _save_student_photo(u_code, photo_bytes):
                            saved_embedded_images += 1
            else:
                flash(request, "XLSX file format not recognized as TASS format.", "danger")
                return RedirectResponse("/courses/create", status_code=303)

        except Exception as e:
            session.rollback()
            flash(request, f"Error processing file: {e}", "danger")
            import traceback
            traceback.print_exc()
            return RedirectResponse("/courses/create", status_code=303)

    if not course_name:
        flash(request, "Course name is required.", "danger")
        return RedirectResponse("/courses/create", status_code=303)

    # Get or create course
    c = session.query(Course).filter_by(name=course_name, semester=semester, year=year).first()
    is_new_course = c is None
    if not c:
        c = Course(name=course_name, semester=semester, year=year)
        session.add(c)
        session.flush()

    for u in students_to_enroll:
        if u not in c.students:
            c.students.append(u)

    session.commit()
    flash(
        request,
        f"Course '{course_name}' {'created' if is_new_course else 'updated'} and {len(students_to_enroll)} students enrolled. "
        f"Saved {saved_embedded_images} embedded photos.",
        "success",
    )

    image_codes = sorted(set(student_codes_for_images))
    if image_codes:
        return render_template(
            "courses/image_sync.html",
            {
                "request": request,
                "current_user": current_user,
                "course_id": c.id,
                "student_codes": image_codes,
            },
        )

    return RedirectResponse("/courses/", status_code=303)


@router.post("/student-images", name="courses.save_student_image")
async def save_student_image(
    request: Request,
    code: str = Form(...),
    image: UploadFile = File(...),
    current_user: User | AnonymousUser = Depends(require_user),
):
    _ = current_user

    safe_code = _sanitize_student_code(code)
    if not safe_code:
        raise HTTPException(status_code=400, detail="Invalid student code")

    try:
        content = await image.read()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Unable to read image upload: {exc}") from exc

    if not content:
        raise HTTPException(status_code=400, detail="Image payload is empty")

    images_dir = os.path.join("app", "static", "img", "stds")
    os.makedirs(images_dir, exist_ok=True)
    image_path = os.path.join(images_dir, f"{safe_code}.jpg")

    try:
        with Image.open(io.BytesIO(content)) as raw:
            image = raw.convert("RGB")
            image.save(image_path, format="JPEG", quality=90)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save image: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid image data: {exc}") from exc

    return {"ok": True, "code": safe_code, "path": f"/static/img/stds/{safe_code}.jpg"}


@router.get("/proxy-image/{student_code}", name="courses.proxy_student_image")
async def proxy_student_image(
    student_code: str,
    current_user: User | AnonymousUser = Depends(require_user),
):
    _ = current_user

    safe_code = _sanitize_student_code(student_code)
    if not safe_code:
        raise HTTPException(status_code=400, detail="Invalid student code")

    params = {
        "do": "kiosk.general.StudPicContentImage",
        "studentCode": safe_code,
    }

    try:
        async with httpx.AsyncClient(timeout=IMAGE_PROXY_TIMEOUT_SECONDS, follow_redirects=True) as client:
            upstream = await client.get(TASS_IMAGE_URL, params=params)
            upstream.raise_for_status()
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="Timed out retrieving student image") from exc
    except httpx.HTTPStatusError as exc:
        status_code = 404 if exc.response.status_code == 404 else 502
        raise HTTPException(status_code=status_code, detail="Student image not available") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Unable to retrieve student image") from exc

    content = upstream.content
    if not content:
        raise HTTPException(status_code=404, detail="Student image was empty")
    if len(content) > IMAGE_PROXY_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Student image exceeded allowed size")

    media_type = upstream.headers.get("Content-Type", "image/jpeg")
    if not media_type.lower().startswith("image/"):
        raise HTTPException(status_code=502, detail="Upstream returned non-image content")

    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Cache-Control": "public, max-age=3600",
            "X-Content-Type-Options": "nosniff",
        },
    )

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

    students = (
        session.query(User)
        .join(User.roles)
        .filter(Role.name == "student")
        .order_by(User.last_name, User.first_name)
        .all()
    )
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
                registered_method="site",
            )
            u.set_password("ChangeMe123!")
            session.add(u)
            student_role = session.query(Role).filter_by(name="student").first()
            if student_role:
                u.roles.append(student_role)
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
        student_role = session.query(Role).filter_by(name="student").first()
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
                    registered_method="bulk",
                )
                u.set_password("ChangeMe123!")
                if student_role:
                    u.roles.append(student_role)
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
