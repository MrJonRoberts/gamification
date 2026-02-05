from datetime import datetime, timezone
from app.extensions import db

class SeatingPosition(db.Model):
    __tablename__ = "seating_positions"
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    x = db.Column(db.Float, default=0)
    y = db.Column(db.Float, default=0)
    locked = db.Column(db.Boolean, default=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        db.UniqueConstraint("course_id", "user_id", name="uq_seating_course_user"),
    )

    course = db.relationship("Course", backref=db.backref("seating_positions", cascade="all, delete-orphan"))
    user = db.relationship("User", backref="seating_positions")