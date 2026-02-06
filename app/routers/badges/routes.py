from __future__ import annotations
import csv
import io
import os
import zipfile
import re
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db, require_user, AnonymousUser
from app.extensions import db
from app.models import Badge, BadgeGrant, User, Role, Award, AwardBadge
from app.services.images import (
    allowed_image,
    open_image,
    square,
    save_png,
    badge_fallback,
    remove_web_path,
)
from app.services.awarding import grant_badge
from app.templating import render_template
from app.utils import flash

router = APIRouter(prefix="/badges", tags=["badges"])

def _has_role(user: User | AnonymousUser, *roles: str) -> bool:
    return getattr(user, "is_authenticated", False) and getattr(user, "role", "") in roles

@router.get("/", response_class=HTMLResponse, name="badges.list_badges")
def list_badges(
    request: Request,
    current_user: User | AnonymousUser = Depends(require_user),
    session: Session = Depends(get_db),
):
    badges = session.query(Badge).order_by(Badge.name.asc()).all()
    return render_template("badges/list.html", {"request": request, "badges": badges, "current_user": current_user})

@router.get("/create", response_class=HTMLResponse, name="badges.create_badge")
def create_badge_form(
    request: Request,
    current_user: User | AnonymousUser = Depends(require_user),
):
    if not _has_role(current_user, "admin", "issuer"):
        flash(request, "Only staff can create badges.", "danger")
        return RedirectResponse("/badges/", status_code=303)
    return render_template("badges/form.html", {"request": request, "current_user": current_user})

@router.post("/create", name="badges.create_badge_post")
async def create_badge_action(
    request: Request,
    name: str = Form(...),
    description: str = Form(None),
    points: int = Form(0),
    icon: UploadFile = File(None),
    current_user: User | AnonymousUser = Depends(require_user),
    session: Session = Depends(get_db),
):
    if not _has_role(current_user, "admin", "issuer"):
        flash(request, "Only staff can create badges.", "danger")
        return RedirectResponse("/badges/", status_code=303)

    name = name.strip()
    exists = session.query(Badge).filter(func.lower(Badge.name) == name.lower()).first()
    if exists:
        flash(request, "A badge with that name already exists.", "warning")
        return render_template("badges/form.html", {"request": request, "current_user": current_user})

    pil = None
    if icon and icon.filename:
        if not allowed_image(icon.filename):
            flash(request, "Icon must be PNG/JPG/JPEG/WEBP.", "danger")
            return render_template("badges/form.html", {"request": request, "current_user": current_user})
        try:
            contents = await icon.read()
            pil = open_image(io.BytesIO(contents))
        except ValueError:
            flash(request, "The uploaded file isn’t a valid image.", "danger")
            return render_template("badges/form.html", {"request": request, "current_user": current_user})
    else:
        pil = badge_fallback(name)

    icon_path = save_png(square(pil), "icons", name)

    try:
        b = Badge(
            name=name,
            description=description.strip() if description else None,
            icon=icon_path,
            points=points,
            created_by_id=current_user.id,
        )
        session.add(b)
        session.commit()
        flash(request, "Badge created.", "success")
        return RedirectResponse("/badges/", status_code=303)
    except Exception as e:
        session.rollback()
        remove_web_path(icon_path)
        flash(request, "Could not create the badge due to a server error.", "danger")
        return render_template("badges/form.html", {"request": request, "current_user": current_user})

@router.get("/edit/{badge_id}", response_class=HTMLResponse, name="badges.edit_badge")
def edit_badge_form(
    badge_id: int,
    request: Request,
    current_user: User | AnonymousUser = Depends(require_user),
    session: Session = Depends(get_db),
):
    if not _has_role(current_user, "admin"):
        flash(request, "Admin access required.", "danger")
        return RedirectResponse("/badges/", status_code=303)

    badge = session.get(Badge, badge_id)
    if not badge:
        raise HTTPException(status_code=404, detail="Badge not found")

    return render_template("badges/edit.html", {"request": request, "badge": badge, "current_user": current_user})

@router.post("/edit/{badge_id}", name="badges.edit_badge_post")
async def edit_badge_action(
    badge_id: int,
    request: Request,
    name: str = Form(...),
    description: str = Form(None),
    points: int = Form(0),
    icon: UploadFile = File(None),
    current_user: User | AnonymousUser = Depends(require_user),
    session: Session = Depends(get_db),
):
    if not _has_role(current_user, "admin"):
        flash(request, "Admin access required.", "danger")
        return RedirectResponse("/badges/", status_code=303)

    badge = session.get(Badge, badge_id)
    if not badge:
        raise HTTPException(status_code=404, detail="Badge not found")

    new_name = name.strip()
    clash = session.query(Badge).filter(func.lower(Badge.name) == new_name.lower(), Badge.id != badge.id).first()
    if clash:
        flash(request, "Another badge already uses that name.", "warning")
        return render_template("badges/edit.html", {"request": request, "badge": badge, "current_user": current_user})

    old_icon = badge.icon
    badge.name = new_name
    badge.description = description.strip() if description else None
    badge.points = points

    if icon and icon.filename:
        if not allowed_image(icon.filename):
            flash(request, "Icon must be PNG/JPG/JPEG/WEBP.", "danger")
            return render_template("badges/edit.html", {"request": request, "badge": badge, "current_user": current_user})
        try:
            contents = await icon.read()
            pil = open_image(io.BytesIO(contents))
            new_icon = save_png(square(pil), "icons", badge.name)
            badge.icon = new_icon
        except ValueError:
            flash(request, "Uploaded icon is not a valid image.", "danger")
            return render_template("badges/edit.html", {"request": request, "badge": badge, "current_user": current_user})

    try:
        session.commit()
        if old_icon and badge.icon != old_icon:
            remove_web_path(old_icon)
        flash(request, "Badge updated.", "success")
        return RedirectResponse("/badges/", status_code=303)
    except Exception:
        session.rollback()
        flash(request, "Could not update the badge due to a server error.", "danger")
        return render_template("badges/edit.html", {"request": request, "badge": badge, "current_user": current_user})

@router.get("/grant/{badge_id}", response_class=HTMLResponse, name="badges.grant")
def grant_form(
    badge_id: int,
    request: Request,
    current_user: User | AnonymousUser = Depends(require_user),
    session: Session = Depends(get_db),
):
    if not _has_role(current_user, "admin", "issuer"):
        flash(request, "Only staff can grant badges.", "danger")
        return RedirectResponse("/badges/", status_code=303)

    badge = session.get(Badge, badge_id)
    if not badge:
        raise HTTPException(status_code=404, detail="Badge not found")

    students = (
        session.query(User)
        .join(User.roles)
        .filter(Role.name == "student")
        .order_by(User.last_name, User.first_name)
        .all()
    )
    return render_template("badges/grant.html", {"request": request, "badge": badge, "students": students, "current_user": current_user})

@router.post("/grant/{badge_id}", name="badges.grant_post")
def grant_action(
    badge_id: int,
    request: Request,
    user_id: int = Form(...),
    current_user: User | AnonymousUser = Depends(require_user),
    session: Session = Depends(get_db),
):
    if not _has_role(current_user, "admin", "issuer"):
        flash(request, "Only staff can grant badges.", "danger")
        return RedirectResponse("/badges/", status_code=303)

    badge = session.get(Badge, badge_id)
    if not badge:
        raise HTTPException(status_code=404, detail="Badge not found")

    try:
        _, created = grant_badge(user_id=user_id, badge_id=badge.id, issued_by_id=current_user.id)
        flash(request, "Badge granted." if created else "Student already has that badge.", "success" if created else "info")
    except Exception:
        flash(request, "Failed to grant badge.", "danger")

    return RedirectResponse("/badges/", status_code=303)

@router.get("/bulk", response_class=HTMLResponse, name="badges.bulk_badges")
def bulk_badges_form(
    request: Request,
    current_user: User | AnonymousUser = Depends(require_user),
):
    if not _has_role(current_user, "admin", "issuer"):
        flash(request, "Only staff can bulk upload badges.", "danger")
        return RedirectResponse("/badges/", status_code=303)
    return render_template("badges/bulk.html", {"request": request, "current_user": current_user})

@router.post("/bulk", name="badges.bulk_badges_post")
async def bulk_badges_action(
    request: Request,
    zipfile_upload: UploadFile = File(..., alias="zipfile"),
    current_user: User | AnonymousUser = Depends(require_user),
    session: Session = Depends(get_db),
):
    if not _has_role(current_user, "admin", "issuer"):
        flash(request, "Only staff can bulk upload badges.", "danger")
        return RedirectResponse("/badges/", status_code=303)

    if not zipfile_upload.filename.lower().endswith(".zip"):
        flash(request, "Please upload a .zip file.", "warning")
        return RedirectResponse("/badges/bulk", status_code=303)

    saved_files: list[str] = []
    try:
        contents = await zipfile_upload.read()
        with zipfile.ZipFile(io.BytesIO(contents)) as zf:
            csv_members = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if not csv_members:
                raise ValueError("No CSV found in the ZIP.")
            if len(csv_members) > 1:
                raise ValueError("Multiple CSV files found; include exactly one.")
            csv_bytes = zf.read(csv_members[0])

            icon_map: dict[str, str] = {}
            for n in zf.namelist():
                base = os.path.basename(n)
                if base and allowed_image(base):
                    icon_map[base.lower()] = n

            text = io.TextIOWrapper(io.BytesIO(csv_bytes), encoding="utf-8-sig", newline="")
            reader = csv.DictReader(text)
            if not reader.fieldnames:
                raise ValueError("CSV has no header row.")

            cols = {c.strip().lower() for c in reader.fieldnames}
            required = {"name", "points", "description", "icon_name"}
            missing = required - cols
            if missing:
                raise ValueError(f"CSV missing required columns: {', '.join(sorted(missing))}")
            has_award = "award" in cols

            rows: list[tuple[str, int, str | None, str, list[str]]] = []
            names_lower: set[str] = set()
            errors: list[str] = []

            for i, row in enumerate(reader, start=2):
                name = (row.get("name") or "").strip()
                points_raw = (row.get("points") or "").strip()
                description = (row.get("description") or "").strip() or None
                icon_name = (row.get("icon_name") or "").strip()
                award_cell = (row.get("award") or "").strip() if has_award else ""

                if not name:
                    errors.append(f"Line {i}: 'name' is required.")
                    continue

                key = name.lower()
                if key in names_lower:
                    errors.append(f"Line {i}: duplicate badge name '{name}' in CSV.")
                    continue
                names_lower.add(key)

                try:
                    pts = int(points_raw or 0)
                except ValueError:
                    errors.append(f"Line {i}: points '{points_raw}' is not an integer.")
                    continue

                awards_list = [a.strip() for a in re.split(r"[;,]", award_cell) if a.strip()] if award_cell else []
                rows.append((name, pts, description, icon_name, awards_list))

            if names_lower:
                existing_badges = (
                    session.query(Badge.name)
                    .filter(func.lower(Badge.name).in_(list(names_lower)))
                    .all()
                )
                if existing_badges:
                    errors.append("Already exists in DB: " + ", ".join(sorted([b[0] for b in existing_badges])))

            if errors:
                raise ValueError(" • " + " • ".join(errors))

            award_cache: dict[str, Award] = {}
            next_seq: dict[int, int] = {}

            def _get_or_create_award(award_name: str) -> Award:
                key = award_name.strip().lower()
                if key in award_cache:
                    return award_cache[key]
                aw = session.query(Award).filter(func.lower(Award.name) == key).first()
                if not aw:
                    aw = Award(name=award_name.strip(), description=None, points=0, created_by_id=current_user.id)
                    session.add(aw)
                    session.flush()
                award_cache[key] = aw
                if aw.id not in next_seq:
                    max_seq = session.query(func.coalesce(func.max(AwardBadge.sequence), 0)).filter(
                        AwardBadge.award_id == aw.id
                    ).scalar() or 0
                    next_seq[aw.id] = int(max_seq) + 1
                return aw

            created_badges_count = 0
            created_links_count = 0

            for (name, pts, desc, icon_name, awards_list) in rows:
                pil = None
                if icon_name:
                    member = icon_map.get(os.path.basename(icon_name).lower())
                    if member:
                        try:
                            with zf.open(member) as fp:
                                pil = open_image(fp)
                        except Exception:
                            pil = None
                if pil is None:
                    pil = badge_fallback(name)

                icon_path = save_png(square(pil), "icons", name)
                saved_files.append(icon_path)

                b = Badge(
                    name=name,
                    description=desc,
                    icon=icon_path,
                    points=pts,
                    created_by_id=current_user.id,
                )
                session.add(b)
                session.flush()
                created_badges_count += 1

                for aw_name in awards_list:
                    aw = _get_or_create_award(aw_name)
                    exists_link = session.query(AwardBadge).filter_by(award_id=aw.id, badge_id=b.id).first()
                    if not exists_link:
                        seq = next_seq.get(aw.id, 1)
                        session.add(AwardBadge(award_id=aw.id, badge_id=b.id, sequence=seq))
                        next_seq[aw.id] = seq + 1
                        created_links_count += 1

            session.commit()
            msg = f"Bulk upload complete: {created_badges_count} badges created."
            if has_award:
                msg += f" Linked {created_links_count} badge↔award pairs."
            flash(request, msg, "success")
            return RedirectResponse("/badges/", status_code=303)

    except Exception as e:
        session.rollback()
        for web_path in saved_files:
            remove_web_path(web_path)
        flash(request, f"Bulk upload failed. No changes were saved. Details: {e}", "danger")
        return RedirectResponse("/badges/bulk", status_code=303)

@router.get("/bulk-template.csv", name="badges.bulk_badges_template")
def bulk_badges_template(current_user: User | AnonymousUser = Depends(require_user)):
    csv_text = (
        "name,points,description,icon_name,award\n"
        "First Program,10,Submitted your first working program.,first_program.png,Python Starter\n"
        "Debug Detective,15,Fixed a non-trivial bug using print/logging.,debug.png,Python Starter\n"
        "Team Player,5,Helped a peer solve a problem.,,\n"
    )
    return Response(
        csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=badges_template.csv"},
    )
