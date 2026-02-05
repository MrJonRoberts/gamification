from datetime import datetime, timezone
from app.extensions import db
from sqlalchemy import select

class Award(db.Model):
    __tablename__ = "awards"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, unique=True)
    description = db.Column(db.Text, nullable=True)
    icon = db.Column(db.String(255), nullable=True)
    points = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_by = db.relationship("User")

    __table_args__ = (
        db.UniqueConstraint("name", name="uq_award_name"),
        db.Index("ix_award_created_at", "created_at"),
    )

class AwardBadge(db.Model):
    __tablename__ = "award_badges"
    award_id = db.Column(db.Integer, db.ForeignKey("awards.id"), primary_key=True)
    badge_id = db.Column(db.Integer, db.ForeignKey("badges.id"), primary_key=True)
    sequence = db.Column(db.Integer, default=0)

    award = db.relationship("Award", backref=db.backref("award_badges", cascade="all, delete-orphan"))
    badge = db.relationship("Badge")

# Helper: award progress for a user
from .badge import Badge, BadgeGrant

def award_progress(user_id: int, award_id: int):
    rows = db.session.execute(
        select(AwardBadge, Badge, BadgeGrant)
        .join(Badge, AwardBadge.badge_id == Badge.id)
        .outerjoin(BadgeGrant, (BadgeGrant.badge_id == Badge.id) & (BadgeGrant.user_id == user_id))
        .where(AwardBadge.award_id == award_id)
        .order_by(AwardBadge.sequence, Badge.name)
    ).all()

    progress = {}
    for ab, badge, grant in rows:
        progress[badge.id] = dict(
            badge_id=badge.id,
            name=badge.name,
            description=badge.description,
            earned=grant is not None,
            earned_at=getattr(grant, "issued_at", None),
        )
    return progress