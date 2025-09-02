import os
import sqlalchemy
from sqlmodel import Session, SQLModel
from app.db import engine as new_engine
from app.models import * # Import all new models

# --- Configuration ---
# Assume the old database is at the root of the original project
OLD_DB_PATH = os.path.abspath(os.path.join(os.getcwd(), '..', 'instance', 'app.db'))
OLD_DB_URL = f"sqlite:///{OLD_DB_PATH}"

def migrate_data():
    """
    Migrates data from the old Flask app's SQLite database to the new FastAPI app's database.
    """
    print(f"Connecting to old database: {OLD_DB_URL}")
    old_engine = sqlalchemy.create_engine(OLD_DB_URL)

    with Session(old_engine) as old_session, Session(new_engine) as new_session:
        print("Migrating users...")
        users = old_session.execute(sqlalchemy.text("SELECT * FROM users")).fetchall()
        for old_user in users:
            new_user = User(
                id=old_user.id,
                student_code=old_user.student_code,
                email=old_user.email,
                first_name=old_user.first_name,
                last_name=old_user.last_name,
                role=old_user.role,
                password_hash=old_user.password_hash,
                registered_method=old_user.registered_method,
                created_at=old_user.created_at,
                avatar=old_user.avatar,
                is_active=old_user.is_active,
            )
            new_session.add(new_user)
        new_session.commit()

        print("Migrating courses...")
        courses = old_session.execute(sqlalchemy.text("SELECT * FROM courses")).fetchall()
        for old_course in courses:
            new_course = Course(
                id=old_course.id,
                name=old_course.name,
                semester=old_course.semester,
                year=old_course.year,
                created_at=old_course.created_at,
            )
            new_session.add(new_course)
        new_session.commit()

        print("Migrating badges...")
        badges = old_session.execute(sqlalchemy.text("SELECT * FROM badges")).fetchall()
        for old_badge in badges:
            new_badge = Badge(
                id=old_badge.id,
                name=old_badge.name,
                description=old_badge.description,
                icon=old_badge.icon,
                points=old_badge.points,
                created_at=old_badge.created_at,
                created_by_id=old_badge.created_by_id,
            )
            new_session.add(new_badge)
        new_session.commit()

        # ... and so on for all other tables in the correct order.
        # This is a simplified script. A real-world script would need more
        # error handling and might need to handle ID mapping if the primary keys
        # are not preserved.

        print("Data migration complete. (Note: only users, courses, and badges migrated in this script)")

if __name__ == "__main__":
    # Ensure the new database is created before trying to migrate
    SQLModel.metadata.create_all(new_engine)
    migrate_data()
