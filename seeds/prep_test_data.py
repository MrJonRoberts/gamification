from __future__ import annotations

from typing import Dict, Iterable, List

from app.extensions import db
from app.models import Award, AwardBadge, Badge, BadgeGrant, Course, PointLedger, User, WeeklyPattern
from app.services.schedule_services import generate_lessons_for_course, parse_time

from seeds.utils import get_or_create


def _sync_weekly_patterns(course: Course, schedule_specs: Iterable[Dict]) -> None:
    existing = {wp.day_of_week: wp for wp in course.schedules}
    desired_days = set()

    for spec in schedule_specs:
        day = spec["day_of_week"]
        desired_days.add(day)
        pattern = existing.get(day)
        if pattern is None:
            pattern = WeeklyPattern(course_id=course.id, day_of_week=day)
            db.session.add(pattern)
        pattern.start_time = parse_time(spec.get("start_time", "09:00"))
        pattern.end_time = parse_time(spec.get("end_time", "10:00"))
        pattern.room = spec.get("room")
        pattern.is_active = True

    for day, pattern in existing.items():
        if day not in desired_days:
            pattern.is_active = False


def seed_courses(users: Dict[str, User]) -> List[Course]:
    students = users["students"]
    course_specs = [
        {
            "name": "Yr6 Digital Tech",
            "semester": "S2",
            "year": 2025,
            "schedules": [
                {"day_of_week": 0, "start_time": "09:00", "end_time": "10:00", "room": "Lab 1"},
                {"day_of_week": 2, "start_time": "09:00", "end_time": "10:00", "room": "Lab 1"},
            ],
            "students": [students[0], students[1]],
        },
        {
            "name": "Yr10 Python",
            "semester": "S2",
            "year": 2025,
            "schedules": [
                {"day_of_week": 1, "start_time": "11:00", "end_time": "12:00", "room": "Lab 2"},
                {"day_of_week": 3, "start_time": "11:00", "end_time": "12:00", "room": "Lab 2"},
            ],
            "students": [students[1], students[2]],
        },
    ]

    created_courses: List[Course] = []
    for spec in course_specs:
        course, _ = get_or_create(
            Course,
            name=spec["name"],
            semester=spec["semester"],
            year=spec["year"],
            defaults={},
        )
        _sync_weekly_patterns(course, spec["schedules"])

        for student in spec["students"]:
            if student not in course.students:
                course.students.append(student)

        created_courses.append(course)

    db.session.commit()

    for course in created_courses:
        generate_lessons_for_course(course.id)

    return created_courses


def seed_badges_and_awards(users: Dict[str, User]) -> Dict[str, List]:
    issuer = users["issuer"]
    students = users["students"]

    badges: List[Badge] = []
    for badge_spec in [
        {
            "name": "First Program",
            "description": "Submitted your first working program.",
            "points": 10,
        },
        {
            "name": "Debug Detective",
            "description": "Fixed a non-trivial bug using print/logging.",
            "points": 15,
        },
        {
            "name": "Team Player",
            "description": "Helped a peer solve a problem.",
            "points": 5,
        },
    ]:
        badge, _ = get_or_create(
            Badge,
            name=badge_spec["name"],
            defaults={
                "description": badge_spec["description"],
                "points": badge_spec["points"],
                "created_by_id": issuer.id,
            },
        )
        badge.description = badge_spec["description"]
        badge.points = badge_spec["points"]
        badge.created_by_id = issuer.id
        badges.append(badge)

    award, _ = get_or_create(
        Award,
        name="Python Starter",
        defaults={
            "description": "Complete the basics.",
            "points": 20,
            "created_by_id": issuer.id,
        },
    )
    award.description = "Complete the basics."
    award.points = 20
    award.created_by_id = issuer.id

    db.session.flush()

    award_badges = [
        (badges[0], 1),
        (badges[1], 2),
    ]
    for badge, sequence in award_badges:
        link, _ = get_or_create(
            AwardBadge,
            award_id=award.id,
            badge_id=badge.id,
            defaults={"sequence": sequence},
        )
        link.sequence = sequence

    db.session.commit()

    grants = [
        (students[0], badges[0]),
        (students[1], badges[0]),
        (students[1], badges[1]),
    ]
    for student, badge in grants:
        grant, created = get_or_create(
            BadgeGrant,
            user_id=student.id,
            badge_id=badge.id,
            defaults={"issued_by_id": issuer.id},
        )
        if created:
            db.session.flush()
        grant.issued_by_id = issuer.id

        ledger = PointLedger.query.filter_by(
            user_id=student.id,
            delta=badge.points,
            reason=f"Badge: {badge.name}",
            source="badge",
        ).first()
        if ledger is None:
            db.session.add(
                PointLedger(
                    user_id=student.id,
                    delta=badge.points,
                    reason=f"Badge: {badge.name}",
                    source="badge",
                    issued_by_id=issuer.id,
                )
            )

    if not PointLedger.query.filter_by(
        user_id=students[2].id,
        delta=7,
        reason="Weekly effort",
        source="manual",
    ).first():
        db.session.add(
            PointLedger(
                user_id=students[2].id,
                delta=7,
                reason="Weekly effort",
                source="manual",
                issued_by_id=issuer.id,
            )
        )

    db.session.commit()

    return {"badges": badges, "award": award}

