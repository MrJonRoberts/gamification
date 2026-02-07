from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

ROOT_PATH = Path(__file__).resolve().parents[1]
if str(ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(ROOT_PATH))

from sqlalchemy.engine.url import make_url

from app.config import settings
from app.extensions import db
from app.models import (
    Award,
    AwardBadge,
    Badge,
    BadgeGrant,
    Course,
    Group,
    PointLedger,
    Role,
    User,
)
from seeds.prep_test_data import seed_badges_and_awards, seed_courses
from seeds.setup_data import seed_academic_years, seed_groups, seed_roles, seed_users

TEST_EMAILS = {
    "s1@example.com",
    "s2@example.com",
    "s3@example.com",
    "teacher@example.com",
}
TEST_COURSE_KEYS = {
    ("Yr6 Digital Tech", "S2", 2025),
    ("Yr10 Python", "S2", 2025),
}
TEST_BADGE_NAMES = {"First Program", "Debug Detective", "Team Player"}
TEST_AWARD_NAMES = {"Python Starter"}


def _sqlite_database_path() -> Path | None:
    url = make_url(settings.SQLALCHEMY_DATABASE_URI)
    if not url.drivername.startswith("sqlite"):
        return None

    database = url.database
    if not database or database == ":memory:":
        return None

    db_path = Path(database)
    if not db_path.is_absolute():
        db_path = Path(settings.ROOT_PATH) / db_path
    return db_path


def reset_database(backup: bool = True) -> Dict[str, str]:
    db.remove_session()
    db.engine.dispose()

    sqlite_path = _sqlite_database_path()
    backup_path = None

    if sqlite_path and sqlite_path.exists() and backup:
        backups_dir = Path(settings.ROOT_PATH) / "backups"
        backups_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backups_dir / f"{sqlite_path.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{sqlite_path.suffix}"
        shutil.copy2(sqlite_path, backup_path)

    if sqlite_path and sqlite_path.exists():
        sqlite_path.unlink()

    db.create_all()

    return {
        "database": str(sqlite_path) if sqlite_path else settings.SQLALCHEMY_DATABASE_URI,
        "backup": str(backup_path) if backup_path else "",
    }


def reset_admin_users() -> Dict[str, User]:
    roles = seed_roles()
    groups = seed_groups()

    admin_role = roles["admin"]
    issuer_role = roles["issuer"]

    admin_users = (
        db.session.query(User)
        .join(User.roles)
        .filter(Role.id.in_([admin_role.id, issuer_role.id]))
        .distinct()
        .all()
    )

    for user in admin_users:
        db.session.query(PointLedger).filter(PointLedger.user_id == user.id).delete(synchronize_session=False)
        db.session.query(BadgeGrant).filter(BadgeGrant.user_id == user.id).delete(synchronize_session=False)
        db.session.query(BadgeGrant).filter(BadgeGrant.issued_by_id == user.id).delete(synchronize_session=False)
        db.session.delete(user)

    db.session.commit()
    return seed_users(roles, groups)


def seed_test_data(users: Dict[str, User] | None = None) -> None:
    if users is None:
        roles = seed_roles()
        groups = seed_groups()
        users = seed_users(roles, groups)

    seed_academic_years()
    seed_courses(users)
    seed_badges_and_awards(users)


def delete_test_data() -> Dict[str, int]:
    deleted = {"courses": 0, "badges": 0, "awards": 0, "users": 0}

    for course_name, semester, year in TEST_COURSE_KEYS:
        course = db.session.query(Course).filter_by(name=course_name, semester=semester, year=year).first()
        if course:
            db.session.delete(course)
            deleted["courses"] += 1

    awards = db.session.query(Award).filter(Award.name.in_(TEST_AWARD_NAMES)).all()
    for award in awards:
        db.session.query(AwardBadge).filter(AwardBadge.award_id == award.id).delete(synchronize_session=False)
        db.session.delete(award)
        deleted["awards"] += 1

    badges = db.session.query(Badge).filter(Badge.name.in_(TEST_BADGE_NAMES)).all()
    for badge in badges:
        db.session.query(BadgeGrant).filter(BadgeGrant.badge_id == badge.id).delete(synchronize_session=False)
        db.session.delete(badge)
        deleted["badges"] += 1

    test_users = db.session.query(User).filter(User.email.in_(TEST_EMAILS)).all()
    for user in test_users:
        db.session.query(PointLedger).filter(
            (PointLedger.user_id == user.id) | (PointLedger.issued_by_id == user.id)
        ).delete(synchronize_session=False)
        db.session.query(BadgeGrant).filter(
            (BadgeGrant.user_id == user.id) | (BadgeGrant.issued_by_id == user.id)
        ).delete(synchronize_session=False)
        db.session.delete(user)
        deleted["users"] += 1

    db.session.commit()
    return deleted


def run_reset_and_seed() -> None:
    db_result = reset_database(backup=True)
    print(f"Database reset complete: {db_result['database']}")
    if db_result["backup"]:
        print(f"Backup created: {db_result['backup']}")

    seed_academic_years()
    roles = seed_roles()
    groups = seed_groups()
    users = seed_users(roles, groups)
    seed_courses(users)
    seed_badges_and_awards(users)
    print("Database seeded. Admin login: admin@example.com / Admin123!")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Database lifecycle and seed-data management utilities.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    reset_db = subparsers.add_parser("reset-database", help="Backup, delete, and recreate the database.")
    reset_db.add_argument("--no-backup", action="store_true", help="Skip creating a backup before reset.")

    subparsers.add_parser("reset-admin-users", help="Reset admin/issuer accounts to seeded defaults.")
    subparsers.add_parser("seed-test-data", help="Seed test students, courses, badges, and awards.")
    subparsers.add_parser("delete-test-data", help="Delete test students, courses, badges, and awards.")
    subparsers.add_parser("reset-and-seed", help="Full reset + default base/test seed data.")

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    try:
        if args.command == "reset-database":
            result = reset_database(backup=not args.no_backup)
            print(f"Database recreated at: {result['database']}")
            if result["backup"]:
                print(f"Backup created at: {result['backup']}")

        elif args.command == "reset-admin-users":
            users = reset_admin_users()
            print(f"Admin users reset. Admin: {users['admin'].email} Issuer: {users['issuer'].email}")

        elif args.command == "seed-test-data":
            seed_test_data()
            print("Test data seeded.")

        elif args.command == "delete-test-data":
            deleted = delete_test_data()
            print(
                "Deleted test data: "
                f"{deleted['users']} users, {deleted['courses']} courses, "
                f"{deleted['badges']} badges, {deleted['awards']} awards"
            )

        elif args.command == "reset-and-seed":
            run_reset_and_seed()
    finally:
        db.remove_session()


if __name__ == "__main__":
    main()
