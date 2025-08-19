from datetime import datetime
from app.extensions import db

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

    __table_args__ = (
        db.CheckConstraint("delta <> 0", name="ck_ledger_delta_nonzero"),
        db.Index("ix_ledger_user_id", "user_id"),
        db.Index("ix_ledger_created_at", "created_at"),
    )

# Helper: total points for a user

def user_total_points(user_id: int) -> int:
    total = db.session.execute(
        db.select(db.func.coalesce(db.func.sum(PointLedger.delta), 0)).where(PointLedger.user_id == user_id)
    ).scalar_one()
    return int(total)