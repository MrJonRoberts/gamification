from __future__ import annotations
import os, sys, runpy, importlib.util, secrets, io, csv
from datetime import datetime
from typing import List, Optional
import pandas as pd
from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile, File, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import or_, func
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db, require_user, AnonymousUser
from app.models import User, AcademicYear, Term, PublicHoliday
from app.models.user import Role, Group
from app.services.schedule_parser import fetch_term_dates, fetch_public_holidays, TERM_DATES_URL, PUBLIC_HOLIDAYS_URL
from app.templating import render_template
from app.utils import flash
from app.config import settings

router = APIRouter(prefix="/admin", tags=["admin"])

def admin_required(user: User = Depends(require_user)):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user

def paginate(query, page, per_page):
    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()
    pages = (total + per_page - 1) // per_page
    return type('Pagination', (), {
        "items": items,
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": pages,
        "has_prev": page > 1,
        "has_next": page < pages,
        "prev_num": page - 1,
        "next_num": page + 1,
        "iter_pages": lambda: range(1, pages + 1)
    })

def _load_and_run_seed():
    seed_path = os.path.join(settings.ROOT_PATH, "seeds/seed.py")
    if not os.path.exists(seed_path):
        raise RuntimeError(f"seed.py not found at {seed_path}")

    if settings.ROOT_PATH not in sys.path:
        sys.path.insert(0, settings.ROOT_PATH)

    spec = importlib.util.spec_from_file_location("seed", seed_path)
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    if hasattr(seed, "main") and callable(seed.main):
        seed.main()
    else:
        runpy.run_path(seed_path, run_name="__main__")

@router.get("/db-tools", response_class=HTMLResponse, name="admin.db_tools")
def db_tools(
    request: Request,
    current_user: User = Depends(admin_required),
):
    return render_template("admin/db_tools.html", {"request": request, "db_uri": settings.SQLALCHEMY_DATABASE_URI, "current_user": current_user})

@router.post("/db-tools/reset-seed", name="admin.reset_seed")
def reset_seed(
    request: Request,
    confirm_text: str = Form(...),
    clean_icons: bool = Form(False),
    current_user: User = Depends(admin_required),
):
    if confirm_text.strip().upper() != "RESET":
        flash(request, 'Type "RESET" to confirm.', "warning")
        return RedirectResponse("/admin/db-tools", status_code=303)

    if clean_icons:
        icons_dir = os.path.join(settings.ROOT_PATH, "app", "static", "icons")
        if os.path.isdir(icons_dir):
            for name in os.listdir(icons_dir):
                p = os.path.join(icons_dir, name)
                if os.path.isfile(p) and not name.startswith("."):
                    try:
                        os.remove(p)
                    except OSError:
                        pass

    try:
        _load_and_run_seed()
    except Exception as e:
        flash(request, f"Reset failed: {e}", "danger")
        return RedirectResponse("/admin/db-tools", status_code=303)

    response = RedirectResponse("/auth/login", status_code=303)
    response.delete_cookie(settings.AUTH_COOKIE_NAME)
    request.session.pop("user_id", None)
    flash(request, "Database reset & seed complete. Please log in with the seeded admin.", "success")
    return response

@router.get("/users", response_class=HTMLResponse, name="admin.users_index")
def users_index(
    request: Request,
    q: str = "",
    role: str = "",
    group: str = "",
    page: int = 1,
    current_user: User = Depends(admin_required),
    session: Session = Depends(get_db),
):
    per_page = 15
    query = session.query(User)

    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                User.email.ilike(like),
                User.first_name.ilike(like),
                User.last_name.ilike(like),
                User.student_code.ilike(like),
            )
        )

    if role:
        query = query.join(User.roles).filter(Role.name == role)

    if group:
        query = query.join(User.groups).filter(Group.name == group)

    query = query.order_by(User.created_at.desc())
    pagination = paginate(query, page, per_page)

    roles = session.query(Role).order_by(Role.name.asc()).all()
    groups = session.query(Group).order_by(Group.name.asc()).all()

    return render_template(
        "admin/users/index.html",
        {
            "request": request,
            "users": pagination.items,
            "pagination": pagination,
            "q": q,
            "role": role,
            "group": group,
            "roles": roles,
            "groups": groups,
            "current_user": current_user,
        }
    )

@router.get("/users/{user_id}/edit", response_class=HTMLResponse, name="admin.users_edit")
def users_edit_form(
    user_id: int,
    request: Request,
    current_user: User = Depends(admin_required),
    session: Session = Depends(get_db),
):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    roles = session.query(Role).order_by(Role.name).all()
    groups = session.query(Group).order_by(Group.name).all()

    return render_template(
        "admin/users/edit.html",
        {
            "request": request,
            "u": user,
            "roles": roles,
            "groups": groups,
            "current_user": current_user,
        }
    )

@router.post("/users/{user_id}/edit", name="admin.users_edit_post")
def users_edit_action(
    user_id: int,
    request: Request,
    first_name: str = Form(...),
    last_name: str = Form(...),
    email: str = Form(...),
    student_code: str = Form(None),
    is_active: bool = Form(True),
    registration_method: str = Form("site"),
    role_ids: List[int] = Form([], alias="roles"),
    group_ids: List[int] = Form([], alias="groups"),
    current_user: User = Depends(admin_required),
    session: Session = Depends(get_db),
):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.first_name = first_name.strip()
    user.last_name = last_name.strip()
    user.email = email.strip().lower()
    user.student_code = (student_code or "").strip() or None
    user.is_active = is_active
    user.registered_method = registration_method

    if role_ids:
        user.roles = session.query(Role).filter(Role.id.in_(role_ids)).all()
    else:
        user.roles = []

    if group_ids:
        user.groups = session.query(Group).filter(Group.id.in_(group_ids)).all()
    else:
        user.groups = []

    session.commit()
    flash(request, "User updated.", "success")
    return RedirectResponse("/admin/users", status_code=303)

@router.post("/users/{user_id}/toggle", name="admin.users_toggle_active")
def users_toggle_active(
    user_id: int,
    request: Request,
    current_user: User = Depends(admin_required),
    session: Session = Depends(get_db),
):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = not user.is_active
    session.commit()
    flash(request, f"User {'activated' if user.is_active else 'deactivated'}.", "success")
    return RedirectResponse(request.headers.get("referer", "/admin/users"), status_code=303)

@router.post("/users/{user_id}/reset-password", name="admin.users_reset_password")
def users_reset_password(
    user_id: int,
    request: Request,
    current_user: User = Depends(admin_required),
    session: Session = Depends(get_db),
):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    new_password = secrets.token_urlsafe(10)
    user.set_password(new_password)
    session.commit()
    flash(request, f"Temporary password set: {new_password}", "warning")
    return RedirectResponse(request.headers.get("referer", "/admin/users"), status_code=303)

@router.post("/users/{user_id}/delete", name="admin.users_delete")
def users_delete(
    user_id: int,
    request: Request,
    current_user: User = Depends(admin_required),
    session: Session = Depends(get_db),
):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    session.delete(user)
    session.commit()
    flash(request, "User deleted.", "success")
    return RedirectResponse("/admin/users", status_code=303)

@router.get("/users/bulk-upload", response_class=HTMLResponse, name="admin.users_bulk_upload")
def bulk_upload_form(
    request: Request,
    current_user: User = Depends(admin_required),
):
    return render_template("admin/users/bulk_upload.html", {"request": request, "current_user": current_user})

@router.post("/users/bulk-upload", name="admin.users_bulk_upload_post")
async def bulk_upload_action(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(admin_required),
    session: Session = Depends(get_db),
):
    filename = file.filename.lower()
    if not (filename.endswith(".csv") or filename.endswith(".xlsx")):
        flash(request, "Please upload a CSV or XLSX file.", "warning")
        return RedirectResponse("/admin/users/bulk-upload", status_code=303)

    try:
        content = await file.read()
        created = 0
        updated = 0
        role_cache = {r.name: r for r in session.query(Role).all()}

        def get_or_create_group(name):
            if not name: return None
            name = str(name).strip()
            if not name or name.lower() == 'nan': return None
            g = session.query(Group).filter_by(name=name).first()
            if not g:
                g = Group(name=name)
                session.add(g)
                session.flush()
            return g

        if filename.endswith(".csv"):
            text = content.decode("utf-8")
            reader = csv.DictReader(io.StringIO(text))

            # Normalize column names to lowercase/stripped
            if reader.fieldnames:
                reader.fieldnames = [c.strip().lower() for c in reader.fieldnames]

            required = {"email", "first_name", "last_name", "role", "password_hash"}
            if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
                missing = required - set(reader.fieldnames or [])
                flash(request, f"Missing columns: {', '.join(missing)}", "danger")
                return RedirectResponse("/admin/users/bulk-upload", status_code=303)

            for row in reader:
                email = (row.get('email') or '').strip().lower()
                if not email:
                    continue

                user = session.query(User).filter_by(email=email).first()
                is_new = False
                if not user:
                    user = User(email=email)
                    session.add(user)
                    is_new = True

                user.first_name = (row.get('first_name') or '').strip()
                user.last_name = (row.get('last_name') or '').strip()
                user.student_code = (row.get('student_code') or '').strip() or None
                user.password_hash = (row.get('password_hash') or '').strip()
                user.registered_method = (row.get('registered_method') or 'bulk').strip()
                user.is_active = (row.get('is_active') or 'True').strip().lower() == 'true'
                user.avatar = (row.get('avatar') or '').strip() or None

                # Handle created_at if provided
                created_at_str = row.get('created_at')
                if created_at_str:
                    try:
                        user.created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                    except ValueError:
                        pass

                # Handle Role
                role_name = (row.get('role') or '').strip().lower()
                if role_name in role_cache:
                    role_obj = role_cache[role_name]
                    if role_obj not in user.roles:
                        user.roles = [role_obj]

                if is_new:
                    created += 1
                else:
                    updated += 1

        else: # .xlsx
            df_full = pd.read_excel(io.BytesIO(content), header=None)

            # Detect TASS format
            is_tass = False
            if len(df_full) > 2:
                row0 = str(df_full.iloc[0, 0]).upper()
                if "TRINITY ANGLICAN SCHOOL" in row0 and "CLASS LISTING" in row0:
                    is_tass = True

            if is_tass:
                # Group from Row 3 (index 2)
                class_info = str(df_full.iloc[2, 0]).strip()
                # Headers are in Row 2 (index 1)
                df = pd.read_excel(io.BytesIO(content), header=1)
                # Skip the class info row which is now the first row of data
                df = df.iloc[1:]
                # Drop summary rows
                df = df[df['Code'].notna()]
                df = df[~df['Code'].astype(str).str.contains("Students in Class", na=False)]

                student_role = role_cache.get('student')
                class_group = get_or_create_group(class_info)

                for _, row in df.iterrows():
                    email = str(row.get('Email', '')).strip().lower()
                    if not email or email == 'nan':
                        continue

                    student_code = str(row.get('Code', '')).strip()
                    if student_code.endswith('.0'): # handle float conversion from excel
                        student_code = student_code[:-2]

                    user = session.query(User).filter_by(email=email).first()
                    is_new = False
                    if not user:
                        user = User(email=email)
                        session.add(user)
                        is_new = True
                        user.set_password(student_code) # Default password is their code

                    # Split Name: "Lastname, Firstname Middlename"
                    name_str = str(row.get('Student Name', ''))
                    if ',' in name_str:
                        last, first = name_str.split(',', 1)
                        user.first_name = first.strip()
                        user.last_name = last.strip()
                    else:
                        user.first_name = name_str
                        user.last_name = ""

                    user.student_code = student_code
                    user.registered_method = 'bulk-tass'

                    if student_role and student_role not in user.roles:
                        user.roles.append(student_role)

                    # Group Assignments
                    if class_group and class_group not in user.groups:
                        user.groups.append(class_group)

                    # Year Group
                    year = row.get('Year')
                    if year and not pd.isna(year):
                        yg = get_or_create_group(f"Year {int(float(year))}")
                        if yg and yg not in user.groups:
                            user.groups.append(yg)

                    # House
                    house = row.get('House')
                    if house and not pd.isna(house):
                        hg = get_or_create_group(f"House {house}")
                        if hg and hg not in user.groups:
                            user.groups.append(hg)

                    # PC/Tutor Group
                    pc = row.get('PC/Tutor Group')
                    if pc and not pd.isna(pc):
                        pg = get_or_create_group(f"PC {pc}")
                        if pg and pg not in user.groups:
                            user.groups.append(pg)

                    if is_new:
                        created += 1
                    else:
                        updated += 1
            else:
                # Standard XLSX (matching CSV columns)
                df = pd.read_excel(io.BytesIO(content))
                df.columns = [c.strip().lower() for c in df.columns]
                required = {"email", "first_name", "last_name", "role", "password_hash"}
                if not required.issubset(set(df.columns)):
                    flash(request, "XLSX file format not recognized. Use TASS format or standard columns.", "danger")
                    return RedirectResponse("/admin/users/bulk-upload", status_code=303)

                for _, row in df.iterrows():
                    email = str(row.get('email', '')).strip().lower()
                    if not email or email == 'nan':
                        continue

                    user = session.query(User).filter_by(email=email).first()
                    is_new = False
                    if not user:
                        user = User(email=email)
                        session.add(user)
                        is_new = True

                    user.first_name = str(row.get('first_name', '')).strip()
                    user.last_name = str(row.get('last_name', '')).strip()
                    sc = str(row.get('student_code', '')).strip()
                    if sc.endswith('.0'): sc = sc[:-2]
                    user.student_code = sc if sc != 'nan' else None
                    user.password_hash = str(row.get('password_hash', '')).strip()
                    user.registered_method = str(row.get('registered_method', 'bulk')).strip()
                    user.is_active = str(row.get('is_active', 'True')).strip().lower() == 'true'
                    av = str(row.get('avatar', '')).strip()
                    user.avatar = av if av != 'nan' else None

                    role_name = str(row.get('role', '')).strip().lower()
                    if role_name in role_cache:
                        role_obj = role_cache[role_name]
                        if role_obj not in user.roles:
                            user.roles = [role_obj]

                    if is_new:
                        created += 1
                    else:
                        updated += 1

        session.commit()
        flash(request, f"Import complete: {created} users created, {updated} updated.", "success")
        return RedirectResponse("/admin/users", status_code=303)

    except Exception as e:
        session.rollback()
        flash(request, f"Error during import: {e}", "danger")
        return RedirectResponse("/admin/users/bulk-upload", status_code=303)

@router.get("/users/bulk-sample.csv", name="admin.users_bulk_sample")
def bulk_sample_csv(current_user: User = Depends(admin_required)):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "student_code", "email", "first_name", "last_name", "role",
        "password_hash", "registered_method", "created_at", "avatar", "is_active"
    ])
    writer.writerow([
        "STU100", "student@example.com", "John", "Doe", "student",
        "argon2$argon2id$v=19$m=65536,t=3,p=4$somehashvalue", "bulk", "2025-01-01T00:00:00", "", "True"
    ])
    return Response(
        output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=users_bulk_sample.csv"}
    )

@router.get("/schedule", response_class=HTMLResponse, name="admin.schedule_index")
def schedule_index(
    request: Request,
    year: Optional[int] = None,
    current_user: User = Depends(admin_required),
    session: Session = Depends(get_db),
):
    if year is None:
        year = datetime.now().year

    academic_year = session.query(AcademicYear).filter_by(year=year).first()

    return render_template(
        "admin/schedule/index.html",
        {
            "request": request,
            "year": year,
            "academic_year": academic_year,
            "default_term_url": TERM_DATES_URL,
            "default_holiday_url": PUBLIC_HOLIDAYS_URL,
            "current_user": current_user,
        }
    )

@router.post("/schedule/fetch", name="admin.schedule_fetch")
def schedule_fetch(
    request: Request,
    year: int = Form(...),
    term_url: str = Form(TERM_DATES_URL),
    holiday_url: str = Form(PUBLIC_HOLIDAYS_URL),
    current_user: User = Depends(admin_required),
    session: Session = Depends(get_db),
):
    try:
        terms_data = fetch_term_dates(year, term_url)
        holidays_data = fetch_public_holidays(year, holiday_url)

        # We don't save yet, just return the data to be displayed and adjusted in a form
        # But wait, the user wants to "display them, allow adjustments... then save"
        # So I'll store them in the session or just pass them back to the template.

        return render_template(
            "admin/schedule/index.html",
            {
                "request": request,
                "year": year,
                "fetched_terms": terms_data,
                "fetched_holidays": holidays_data,
                "term_url": term_url,
                "holiday_url": holiday_url,
                "default_term_url": TERM_DATES_URL,
                "default_holiday_url": PUBLIC_HOLIDAYS_URL,
                "current_user": current_user,
            }
        )
    except Exception as e:
        flash(request, f"Error fetching schedule: {e}", "danger")
        return RedirectResponse(f"/admin/schedule?year={year}", status_code=303)

@router.post("/schedule/save", name="admin.schedule_save")
def schedule_save(
    request: Request,
    year: int = Form(...),
    term_urls: str = Form(""), # source URLs
    # Terms
    term_1_start: Optional[str] = Form(None),
    term_1_end: Optional[str] = Form(None),
    term_2_start: Optional[str] = Form(None),
    term_2_end: Optional[str] = Form(None),
    term_3_start: Optional[str] = Form(None),
    term_3_end: Optional[str] = Form(None),
    term_4_start: Optional[str] = Form(None),
    term_4_end: Optional[str] = Form(None),
    # Holidays - passed as lists
    holiday_names: List[str] = Form([]),
    holiday_dates: List[str] = Form([]),
    current_user: User = Depends(admin_required),
    session: Session = Depends(get_db),
):
    academic_year = session.query(AcademicYear).filter_by(year=year).first()
    if not academic_year:
        academic_year = AcademicYear(year=year)
        session.add(academic_year)

    academic_year.source = term_urls
    academic_year.last_updated = datetime.now().date()

    # Update Terms
    term_map = {t.number: t for t in academic_year.terms}

    starts = [term_1_start, term_2_start, term_3_start, term_4_start]
    ends = [term_1_end, term_2_end, term_3_end, term_4_end]
    for i in range(1, 5):
        start_val = starts[i-1]
        end_val = ends[i-1]

        if start_val and end_val:
            term = term_map.get(i)
            if not term:
                term = Term(academic_year=academic_year, number=i, name=f"Term {i}")
                session.add(term)
            term.start_date = datetime.strptime(start_val, "%Y-%m-%d").date()
            term.end_date = datetime.strptime(end_val, "%Y-%m-%d").date()

    # Update Holidays
    # Simple approach: clear and recreate
    academic_year.holidays = []
    session.flush() # Ensure they are removed before adding new ones to avoid unique constraint issues

    seen_dates = set()
    for name, date_str in zip(holiday_names, holiday_dates):
        name = name.strip()
        date_str = date_str.strip()
        if name and date_str:
            d = datetime.strptime(date_str, "%Y-%m-%d").date()
            if d in seen_dates:
                continue
            seen_dates.add(d)
            holiday = PublicHoliday(
                academic_year=academic_year,
                name=name,
                date=d
            )
            session.add(holiday)

    session.commit()
    flash(request, f"Schedule for {year} saved.", "success")
    return RedirectResponse(f"/admin/schedule?year={year}", status_code=303)
