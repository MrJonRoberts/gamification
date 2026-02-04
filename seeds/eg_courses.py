"""Compatibility wrapper for legacy seed entrypoint."""

from seeds.prep_test_data import seed_courses
from seeds.setup_data import seed_users


def seed_example_courses():
    users = seed_users()
    seed_courses(users)
