from datetime import datetime, timezone
from app.extensions import db

# Association table between users (students) and courses
Enrollment = db.Table(
    "enrollment",
    db.Column("user_id", db.Integer, db.ForeignKey("users.id"), primary_key=True),
    db.Column("course_id", db.Integer, db.ForeignKey("courses.id"), primary_key=True),
)

class Course(db.Model):
    __tablename__ = "courses"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    semester = db.Column(db.String(20), nullable=False)  # "S1" | "S2" | "FULL"
    year = db.Column(db.Integer, nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    students = db.relationship("User", secondary=Enrollment, backref="courses", lazy="dynamic")

    __table_args__ = (
        db.UniqueConstraint("name", "semester", "year", name="uq_course_term"),
        db.Index("ix_course_term", "year", "semester"),
        db.Index("ix_course_created_at", "created_at"),
    )

    @property
    def display_name(self) -> str:
        """Human-readable course label used in templates and flash messages."""
        return f"{self.name} {self.semester} {self.year}"
