from typing import List, Optional, TYPE_CHECKING
from datetime import datetime
from sqlmodel import Field, SQLModel, Relationship
from passlib.context import CryptContext
from .link_models import UserRoleLink, UserGroupLink, Enrollment

if TYPE_CHECKING:
    from .course import Course
    from .badge import Badge, BadgeGrant
    from .point_ledger import PointLedger
    from .behaviour import Behaviour
    from .seating import SeatingPosition
    from .attendance import Attendance

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class Role(SQLModel, table=True):
    __tablename__ = "roles"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True)
    users: List["User"] = Relationship(back_populates="roles", link_model=UserRoleLink)

class Group(SQLModel, table=True):
    __tablename__ = "groups"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True)
    users: List["User"] = Relationship(back_populates="groups", link_model=UserGroupLink)

class User(SQLModel, table=True):
    __tablename__ = "users"

    id: Optional[int] = Field(default=None, primary_key=True)
    student_code: Optional[str] = Field(unique=True)
    email: str = Field(unique=True, index=True)
    first_name: str
    last_name: str
    role: str = "student"
    password_hash: str
    registered_method: str = "site"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    avatar: Optional[str] = None
    is_active: bool = True

    roles: List["Role"] = Relationship(back_populates="users", link_model=UserRoleLink)
    groups: List["Group"] = Relationship(back_populates="users", link_model=UserGroupLink)

    courses: List["Course"] = Relationship(back_populates="students", link_model=Enrollment)

    issued_badges: List["Badge"] = Relationship(back_populates="creator")
    badge_grants: List["BadgeGrant"] = Relationship(back_populates="user", sa_relationship_kwargs={"foreign_keys": "[BadgeGrant.user_id]"})
    issued_badge_grants: List["BadgeGrant"] = Relationship(back_populates="issued_by", sa_relationship_kwargs={"foreign_keys": "[BadgeGrant.issued_by_id]"})

    points: List["PointLedger"] = Relationship(back_populates="user", sa_relationship_kwargs={"foreign_keys": "[PointLedger.user_id]"})
    issued_points: List["PointLedger"] = Relationship(back_populates="issued_by", sa_relationship_kwargs={"foreign_keys": "[PointLedger.issued_by_id]"})

    behaviours: List["Behaviour"] = Relationship(back_populates="user", sa_relationship_kwargs={"foreign_keys": "[Behaviour.user_id]"})
    created_behaviours: List["Behaviour"] = Relationship(back_populates="created_by", sa_relationship_kwargs={"foreign_keys": "[Behaviour.created_by_id]"})

    seating_positions: List["SeatingPosition"] = Relationship(back_populates="user")

    attendances: List["Attendance"] = Relationship(back_populates="student", sa_relationship_kwargs={"foreign_keys": "[Attendance.student_id]"})
    marked_attendances: List["Attendance"] = Relationship(back_populates="marked_by", sa_relationship_kwargs={"foreign_keys": "[Attendance.marked_by_user_id]"})


    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    def set_password(self, password: str):
        self.password_hash = pwd_context.hash(password)

    def check_password(self, password: str) -> bool:
        return pwd_context.verify(password, self.password_hash)
