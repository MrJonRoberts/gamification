from typing import Optional, TYPE_CHECKING
from datetime import datetime
from sqlmodel import Field, SQLModel, Relationship
from sqlalchemy import CheckConstraint

if TYPE_CHECKING:
    from .user import User
    from .course import Course


class PointLedger(SQLModel, table=True):
    __tablename__ = "point_ledger"
    __table_args__ = (
        CheckConstraint("delta <> 0", name="ck_ledger_delta_nonzero"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    delta: int
    reason: Optional[str] = None
    source: str = "manual"
    course_id: Optional[int] = Field(foreign_key="courses.id")
    issued_by_id: Optional[int] = Field(foreign_key="users.id")
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    user: "User" = Relationship(back_populates="points", sa_relationship_kwargs={"foreign_keys": "[PointLedger.user_id]"})
    course: Optional["Course"] = Relationship()
    issued_by: Optional["User"] = Relationship(back_populates="issued_points", sa_relationship_kwargs={"foreign_keys": "[PointLedger.issued_by_id]"})
