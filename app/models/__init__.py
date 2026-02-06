# Re-export models so external code can keep using: from app.models import User, Course, ...
from .user import User, Role, Group
from .course import Course, Enrollment
from .badge import Badge, BadgeGrant
from .award import Award, AwardBadge, award_progress
from .point_ledger import PointLedger, user_total_points
from .behaviour import Behaviour
from .seating import SeatingPosition
from .schedule import AcademicYear, Term, PublicHoliday, WeeklyPattern, Lesson, LessonStatus
from .attendance import Attendance, AttendanceStatus

__all__ = [
    # core
    "User", "Role", "Group", "Course", "Enrollment",
    # badges/awards
    "Badge", "BadgeGrant", "Award", "AwardBadge", "PointLedger",
    # helpers
    "award_progress", "user_total_points",
    # behaviour & seating
    "Behaviour", "SeatingPosition",
    # schedule & attendance
    "AcademicYear", "Term", "PublicHoliday", "WeeklyPattern", "Lesson", "LessonStatus",
    "Attendance", "AttendanceStatus",
]