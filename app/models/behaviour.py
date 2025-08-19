from datetime import datetime
from app.extensions import db

class Behaviour(db.Model):
    __tablename__ = "behaviours"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=True, index=True)
    delta = db.Column(db.Integer, nullable=False)
    note = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    user = db.relationship("User", foreign_keys=[user_id])
    course = db.relationship("Course", foreign_keys=[course_id])
    created_by = db.relationship("User", foreign_keys=[created_by_id])

    __table_args__ = (
        db.CheckConstraint("delta <> 0", name="ck_behaviour_delta_nonzero"),
        db.Index("ix_behaviour_user_created", "user_id", "created_at"),
    )