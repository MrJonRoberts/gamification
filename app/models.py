from datetime import datetime
from .extensions import db
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin

# Association between users (students) and courses
Enrollment = db.Table(
    "enrollment",
    db.Column("user_id", db.Integer, db.ForeignKey("users.id"), primary_key=True),
    db.Column("course_id", db.Integer, db.ForeignKey("courses.id"), primary_key=True),
)

class User(db.Model, UserMixin):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    student_code = db.Column(db.String(32), unique=True, nullable=True)  # for students
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="student")  # student|issuer|admin
    password_hash = db.Column(db.String(255), nullable=False)
    registered_method = db.Column(db.String(20), nullable=False, default="site")  # site|bulk
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    issued_badges = db.relationship("Badge", backref="creator", lazy=True, foreign_keys="Badge.created_by_id")

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

class Course(db.Model):
    __tablename__ = "courses"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    semester = db.Column(db.String(20), nullable=False)  # e.g., "S1", "S2"
    year = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    students = db.relationship("User", secondary=Enrollment, backref="courses", lazy="dynamic")

class Badge(db.Model):
    __tablename__ = "badges"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, unique=True)
    description = db.Column(db.Text, nullable=True)
    icon = db.Column(db.String(255), nullable=True)  # path/URL to icon
    points = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

class BadgeGrant(db.Model):
    __tablename__ = "badge_grants"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    badge_id = db.Column(db.Integer, db.ForeignKey("badges.id"), nullable=False)
    issued_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    issued_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", foreign_keys=[user_id], backref="badge_grants")
    badge = db.relationship("Badge", backref="grants")
    issued_by = db.relationship("User", foreign_keys=[issued_by_id])

class Award(db.Model):
    __tablename__ = "awards"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, unique=True)
    description = db.Column(db.Text, nullable=True)
    icon = db.Column(db.String(255), nullable=True)
    points = db.Column(db.Integer, default=0, nullable=False)  # optional additional points
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_by = db.relationship("User")

class AwardBadge(db.Model):
    __tablename__ = "award_badges"
    award_id = db.Column(db.Integer, db.ForeignKey("awards.id"), primary_key=True)
    badge_id = db.Column(db.Integer, db.ForeignKey("badges.id"), primary_key=True)
    sequence = db.Column(db.Integer, default=0)

    award = db.relationship("Award", backref=db.backref("award_badges", cascade="all, delete-orphan"))
    badge = db.relationship("Badge")

class PointLedger(db.Model):
    __tablename__ = "point_ledger"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    delta = db.Column(db.Integer, nullable=False)  # can be negative
    reason = db.Column(db.String(255), nullable=True)
    source = db.Column(db.String(50), nullable=False, default="manual")  # manual|badge|award
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=True)
    issued_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", foreign_keys=[user_id], backref="points")
    course = db.relationship("Course")
    issued_by = db.relationship("User", foreign_keys=[issued_by_id])

# Helper queries
def user_total_points(user_id:int) -> int:
    total = db.session.execute(db.select(db.func.coalesce(db.func.sum(PointLedger.delta), 0)).where(PointLedger.user_id==user_id)).scalar_one()
    return int(total)

def award_progress(user_id:int, award_id:int):
    # returns dict of {badge_id: {"name":..., "earned":bool, "earned_at":datetime or None}}
    rows = db.session.execute(
        db.select(AwardBadge, Badge, BadgeGrant)
        .join(Badge, AwardBadge.badge_id==Badge.id)
        .outerjoin(BadgeGrant, (BadgeGrant.badge_id==Badge.id) & (BadgeGrant.user_id==user_id))
        .where(AwardBadge.award_id==award_id)
        .order_by(AwardBadge.sequence, Badge.name)
    ).all()
    progress = {}
    for ab, badge, grant in rows:
        progress[badge.id] = dict(
            badge_id=badge.id,
            name=badge.name,
            description=badge.description,
            earned=grant is not None,
            earned_at=getattr(grant, "issued_at", None)
        )
    return progress
