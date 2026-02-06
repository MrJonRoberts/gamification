from __future__ import annotations

from datetime import date
from typing import Any, Dict, List

from app.extensions import db
from app.models import AcademicYear, Group, Role, Term, User

from seeds.utils import get_or_create


TERM_DATE_FIXTURES: List[Dict] = [
    {
        "year": 2025,
        "source": "QLD term dates (static)",
        "terms": [
            {
                "number": 1,
                "name": "Term 1",
                "start_date": date(2025, 1, 28),
                "end_date": date(2025, 4, 4),
                "weeks": 10,
                "raw": "Term 1: 28 January to 4 April — 10 weeks",
            },
            {
                "number": 2,
                "name": "Term 2",
                "start_date": date(2025, 4, 22),
                "end_date": date(2025, 6, 27),
                "weeks": 10,
                "raw": "Term 2: 22 April to 27 June — 10 weeks",
            },
            {
                "number": 3,
                "name": "Term 3",
                "start_date": date(2025, 7, 14),
                "end_date": date(2025, 9, 19),
                "weeks": 10,
                "raw": "Term 3: 14 July to 19 September — 10 weeks",
            },
            {
                "number": 4,
                "name": "Term 4",
                "start_date": date(2025, 10, 7),
                "end_date": date(2025, 12, 12),
                "weeks": 10,
                "raw": "Term 4: 7 October to 12 December — 10 weeks",
            },
        ],
    }
]


def seed_roles() -> Dict[str, Role]:
    roles = {}
    for role_name in ["admin", "issuer", "student"]:
        role, _ = get_or_create(Role, name=role_name)
        roles[role_name] = role
    db.session.commit()
    return roles


def seed_groups() -> Dict[str, Group]:
    groups = {}
    for group_name in ["Year 10", "Year 11", "Year 12", "Staff"]:
        group, _ = get_or_create(Group, name=group_name)
        groups[group_name] = group
    db.session.commit()
    return groups


def seed_users(roles: Dict[str, Role], groups: Dict[str, Group]) -> Dict[str, User]:
    def build_user(**kwargs: Any) -> User:
        from app.security import hash_password

        password = kwargs.pop("password")
        user_roles = kwargs.pop("user_roles", [])
        user_groups = kwargs.pop("user_groups", [])
        kwargs.pop("role", None)

        kwargs["password_hash"] = hash_password(password)
        user, _ = get_or_create(User, email=kwargs["email"], defaults=kwargs)
        for key, value in kwargs.items():
            setattr(user, key, value)

        user.roles = user_roles
        user.groups = user_groups
        return user

    admin = build_user(
        email="admin@example.com",
        first_name="Ada",
        last_name="Admin",
        registered_method="site",
        password="Admin123!",
        user_roles=[roles["admin"]],
        user_groups=[groups["Staff"]],
    )
    issuer = build_user(
        email="teacher@example.com",
        first_name="Terry",
        last_name="Teacher",
        registered_method="site",
        password="Issuer123!",
        user_roles=[roles["issuer"]],
        user_groups=[groups["Staff"]],
    )
    students = [
        build_user(
            student_code="STU001",
            email="s1@example.com",
            first_name="Kai",
            last_name="Nguyen",
            registered_method="site",
            password="ChangeMe123!",
            user_roles=[roles["student"]],
            user_groups=[groups["Year 10"]],
        ),
        build_user(
            student_code="STU002",
            email="s2@example.com",
            first_name="Mia",
            last_name="Singh",
            registered_method="site",
            password="ChangeMe123!",
            user_roles=[roles["student"]],
            user_groups=[groups["Year 11"]],
        ),
        build_user(
            student_code="STU003",
            email="s3@example.com",
            first_name="Noah",
            last_name="Smith",
            registered_method="site",
            password="ChangeMe123!",
            user_roles=[roles["student"]],
            user_groups=[groups["Year 12"]],
        ),
    ]

    db.session.commit()
    return {"admin": admin, "issuer": issuer, "students": students}


def seed_academic_years() -> List[AcademicYear]:
    created_years: List[AcademicYear] = []
    for year_fixture in TERM_DATE_FIXTURES:
        academic_year, created = get_or_create(
            AcademicYear,
            year=year_fixture["year"],
            defaults={"source": year_fixture["source"]},
        )
        academic_year.source = year_fixture["source"]
        if created:
            db.session.flush()

        for term in year_fixture["terms"]:
            term_row, _ = get_or_create(
                Term,
                academic_year_id=academic_year.id,
                number=term["number"],
                defaults={
                    "name": term["name"],
                    "start_date": term["start_date"],
                    "end_date": term["end_date"],
                    "weeks": term["weeks"],
                    "raw": term["raw"],
                },
            )
            term_row.name = term["name"]
            term_row.start_date = term["start_date"]
            term_row.end_date = term["end_date"]
            term_row.weeks = term["weeks"]
            term_row.raw = term["raw"]

        created_years.append(academic_year)

    db.session.commit()
    return created_years

