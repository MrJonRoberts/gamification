from app.extensions import db
from seeds.prep_test_data import seed_badges_and_awards, seed_courses
from seeds.setup_data import (
    seed_academic_years,
    seed_groups,
    seed_houses,
    seed_homerooms,
    seed_roles,
    seed_users,
)


def main():
    try:
        db.drop_all()
        db.create_all()

        seed_academic_years()
        roles = seed_roles()
        groups = seed_groups()
        houses = seed_houses()
        homerooms = seed_homerooms()
        users = seed_users(roles, groups, houses, homerooms)
        seed_courses(users)
        seed_badges_and_awards(users)

        print("Database seeded. Admin login: admin@example.com / Admin123!")
    finally:
        db.remove_session()


if __name__ == '__main__':
    main()
