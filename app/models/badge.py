from datetime import datetime, timezone
from app.extensions import db

class Badge(db.Model):
    __tablename__ = "badges"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, unique=True)
    description = db.Column(db.Text, nullable=True)
    icon = db.Column(db.String(255), nullable=True)
    points = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    __table_args__ = (
        db.CheckConstraint("points >= 0", name="ck_badge_points_nonneg"),
        db.Index("ix_badge_name", "name"),
        db.Index("ix_badge_created_at", "created_at"),
    )

class BadgeGrant(db.Model):
    __tablename__ = "badge_grants"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    badge_id = db.Column(db.Integer, db.ForeignKey("badges.id"), nullable=False)
    issued_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    issued_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship("User", foreign_keys=[user_id], backref="badge_grants")
    badge = db.relationship("Badge", backref="grants")
    issued_by = db.relationship("User", foreign_keys=[issued_by_id])

    __table_args__ = (
        db.UniqueConstraint("user_id", "badge_id", name="uq_grant_user_badge"),
        db.Index("ix_grant_user_id", "user_id"),
        db.Index("ix_grant_badge_id", "badge_id"),
        db.Index("ix_grant_issued_at", "issued_at"),
    )