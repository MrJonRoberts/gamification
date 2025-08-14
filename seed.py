from app import create_app, db
from app.models import User, Course, Badge, Award, AwardBadge, BadgeGrant, PointLedger
from datetime import datetime

app = create_app()
with app.app_context():
    db.drop_all()
    db.create_all()

    # Staff
    admin = User(email="admin@example.com", first_name="Ada", last_name="Admin", role="admin", registered_method="site")
    admin.set_password("Admin123!")
    issuer = User(email="teacher@example.com", first_name="Terry", last_name="Teacher", role="issuer", registered_method="site")
    issuer.set_password("Issuer123!")

    # Students
    s1 = User(student_code="STU001", email="s1@example.com", first_name="Kai", last_name="Nguyen", role="student", registered_method="site"); s1.set_password("ChangeMe123!")
    s2 = User(student_code="STU002", email="s2@example.com", first_name="Mia", last_name="Singh", role="student", registered_method="site"); s2.set_password("ChangeMe123!")
    s3 = User(student_code="STU003", email="s3@example.com", first_name="Noah", last_name="Smith", role="student", registered_method="site"); s3.set_password("ChangeMe123!")

    db.session.add_all([admin, issuer, s1, s2, s3])
    db.session.commit()

    # Courses
    c1 = Course(name="Yr6 Digital Tech", semester="S2", year=2025)
    c2 = Course(name="Yr10 Python", semester="S2", year=2025)
    db.session.add_all([c1, c2]); db.session.commit()

    c1.students.append(s1); c1.students.append(s2)
    c2.students.append(s2); c2.students.append(s3)
    db.session.commit()

    # Badges
    b1 = Badge(name="First Program", description="Submitted your first working program.", points=10, created_by_id=issuer.id)
    b2 = Badge(name="Debug Detective", description="Fixed a non-trivial bug using print/logging.", points=15, created_by_id=issuer.id)
    b3 = Badge(name="Team Player", description="Helped a peer solve a problem.", points=5, created_by_id=issuer.id)
    db.session.add_all([b1, b2, b3]); db.session.commit()

    # Awards (composed of badges)
    a1 = Award(name="Python Starter", description="Complete the basics.", points=20, created_by_id=issuer.id)
    db.session.add(a1); db.session.flush()
    db.session.add_all([AwardBadge(award_id=a1.id, badge_id=b1.id, sequence=1),
                        AwardBadge(award_id=a1.id, badge_id=b2.id, sequence=2)])
    db.session.commit()

    # Grants & points
    db.session.add_all([
        BadgeGrant(user_id=s1.id, badge_id=b1.id, issued_by_id=issuer.id),
        PointLedger(user_id=s1.id, delta=b1.points, reason=f"Badge: {b1.name}", source="badge", issued_by_id=issuer.id),
        BadgeGrant(user_id=s2.id, badge_id=b1.id, issued_by_id=issuer.id),
        PointLedger(user_id=s2.id, delta=b1.points, reason=f"Badge: {b1.name}", source="badge", issued_by_id=issuer.id),
        BadgeGrant(user_id=s2.id, badge_id=b2.id, issued_by_id=issuer.id),
        PointLedger(user_id=s2.id, delta=b2.points, reason=f"Badge: {b2.name}", source="badge", issued_by_id=issuer.id),
        PointLedger(user_id=s3.id, delta=7, reason="Weekly effort", source="manual", issued_by_id=issuer.id),
    ])
    db.session.commit()

    print("Database seeded. Admin login: admin@example.com / Admin123!")
