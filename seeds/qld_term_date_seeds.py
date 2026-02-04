"""Seed Queensland term dates using the current academic year model."""

from seeds.setup_data import seed_academic_years


def seed_qld_term_dates():
    return seed_academic_years()
