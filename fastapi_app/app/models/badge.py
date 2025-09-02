from typing import List, Optional, TYPE_CHECKING
from datetime import datetime
from sqlmodel import Field, SQLModel, Relationship
from sqlalchemy import CheckConstraint, UniqueConstraint
from .link_models import AwardBadge

if TYPE_CHECKING:
    from .user import User
    from .award import Award


class Badge(SQLModel, table=True):
    __tablename__ = "badges"
    __table_args__ = (
        CheckConstraint("points >= 0", name="ck_badge_points_nonneg"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    description: Optional[str] = None
    icon: Optional[str] = None
    points: int = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    created_by_id: Optional[int] = Field(foreign_key="users.id")

    creator: Optional["User"] = Relationship(back_populates="issued_badges")
    grants: List["BadgeGrant"] = Relationship(back_populates="badge")
    awards: List["Award"] = Relationship(back_populates="badges", link_model=AwardBadge)


class BadgeGrant(SQLModel, table=True):
    __tablename__ = "badge_grants"
    __table_args__ = (
        UniqueConstraint("user_id", "badge_id", name="uq_grant_user_badge"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    badge_id: int = Field(foreign_key="badges.id", index=True)
    issued_by_id: Optional[int] = Field(foreign_key="users.id")
    issued_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    user: "User" = Relationship(back_populates="badge_grants", sa_relationship_kwargs={"foreign_keys": "[BadgeGrant.user_id]"})
    badge: "Badge" = Relationship(back_populates="grants")
    issued_by: Optional["User"] = Relationship(back_populates="issued_badge_grants", sa_relationship_kwargs={"foreign_keys": "[BadgeGrant.issued_by_id]"})
