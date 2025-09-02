from typing import Optional, TYPE_CHECKING
from datetime import datetime
from sqlmodel import Field, SQLModel, Relationship
from sqlalchemy import CheckConstraint, Index

if TYPE_CHECKING:
    from .user import User
    from .course import Course


class Behaviour(SQLModel, table=True):
    __tablename__ = "behaviours"
    __table_args__ = (
        CheckConstraint("delta <> 0", name="ck_behaviour_delta_nonzero"),
        Index("ix_behaviour_user_created", "user_id", "created_at"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    course_id: Optional[int] = Field(foreign_key="courses.id", index=True)
    delta: int
    note: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    created_by_id: int = Field(foreign_key="users.id")

    user: "User" = Relationship(back_populates="behaviours", sa_relationship_kwargs={"foreign_keys": "[Behaviour.user_id]"})
    course: Optional["Course"] = Relationship()
    created_by: "User" = Relationship(back_populates="created_behaviours", sa_relationship_kwargs={"foreign_keys": "[Behaviour.created_by_id]"})
