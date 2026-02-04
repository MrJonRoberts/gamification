from app import create_app, db
from seeds.prep_test_data import seed_badges_and_awards, seed_courses
from seeds.setup_data import seed_academic_years, seed_users

def main():
    app = create_app()
    with app.app_context():
        db.drop_all()
        db.create_all()

        seed_academic_years()
        users = seed_users()
        seed_courses(users)
        seed_badges_and_awards(users)

        print("Database seeded. Admin login: admin@example.com / Admin123!")


if __name__ == '__main__':
    main()
