from sqlmodel import Field, SQLModel

class UserRoleLink(SQLModel, table=True):
    __tablename__ = "user_roles"
    user_id: int = Field(foreign_key="users.id", primary_key=True)
    role_id: int = Field(foreign_key="roles.id", primary_key=True)

class UserGroupLink(SQLModel, table=True):
    __tablename__ = "user_groups"
    user_id: int = Field(foreign_key="users.id", primary_key=True)
    group_id: int = Field(foreign_key="groups.id", primary_key=True)

class Enrollment(SQLModel, table=True):
    __tablename__ = "enrollment"
    user_id: int = Field(foreign_key="users.id", primary_key=True)
    course_id: int = Field(foreign_key="courses.id", primary_key=True)

class AwardBadge(SQLModel, table=True):
    __tablename__ = "award_badges"
    award_id: int = Field(foreign_key="awards.id", primary_key=True)
    badge_id: int = Field(foreign_key="badges.id", primary_key=True)
    sequence: int = Field(default=0)
