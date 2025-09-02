from sqlmodel import Session, select
from app.db import engine
from app.models.user import User

def create_admin_user():
    """
    Creates a default admin user if one doesn't already exist.
    """
    with Session(engine) as session:
        # Check if the admin user already exists
        admin_user = session.exec(select(User).where(User.email == "admin@example.com")).first()
        if admin_user:
            print("Admin user already exists.")
            return

        # Create the new admin user
        print("Creating admin user...")
        admin_user = User(
            first_name="Admin",
            last_name="User",
            email="admin@example.com",
            role="admin",
        )
        admin_user.set_password("admin")
        session.add(admin_user)
        session.commit()
        print("Admin user created successfully.")

if __name__ == "__main__":
    create_admin_user()
