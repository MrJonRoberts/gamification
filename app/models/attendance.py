from app.extensions import db

class AttendanceStatus:
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    LATE = "LATE"
    SCHOOL_APPROVED_ABSENT = "SCHOOL_APPROVED_ABSENT"
    NO_CLASS_TODAY = "NO_CLASS_TODAY"

class Attendance(db.Model):
    __tablename__ = "attendance"

    id = db.Column(db.Integer, primary_key=True)
    lesson_id = db.Column(db.Integer, db.ForeignKey("lessons.id"), nullable=False)

    # Two different FKs to users
    student_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    marked_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    status = db.Column(
        db.Enum(
            AttendanceStatus.PRESENT,
            AttendanceStatus.ABSENT,
            AttendanceStatus.LATE,
            AttendanceStatus.SCHOOL_APPROVED_ABSENT,
            AttendanceStatus.NO_CLASS_TODAY,
            name="attendance_status",
        ),
        nullable=False,
        default=AttendanceStatus.PRESENT,
    )
    marked_at = db.Column(db.DateTime, server_default=db.func.now())
    comment = db.Column(db.String(255))

    lesson = db.relationship(
        "Lesson",
        backref=db.backref("attendance", cascade="all, delete-orphan")
    )

    # Make the FK path explicit and pair with back_populates on User
    student = db.relationship(
        "User",
        foreign_keys=[student_id],
        back_populates="attendances",
    )
    marked_by = db.relationship(
        "User",
        foreign_keys=[marked_by_user_id],
        back_populates="marked_attendances",
    )

    __table_args__ = (
        db.UniqueConstraint("lesson_id", "student_id", name="uq_attendance_unique"),
        db.Index("ix_attendance_lesson", "lesson_id"),
        db.Index("ix_attendance_student", "student_id"),
    )

    def __repr__(self):
        return f"<Attendance id={self.id} lesson_id={self.lesson_id} student_id={self.student_id} status={self.status}>"
