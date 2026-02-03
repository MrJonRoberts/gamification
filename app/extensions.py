from __future__ import annotations

from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    Time,
    UniqueConstraint,
    create_engine,
    func,
    select,
)
from sqlalchemy.orm import (
    backref,
    declarative_base,
    relationship,
    scoped_session,
    sessionmaker,
)

Base = declarative_base()


class Database:
    Model = Base
    Column = Column
    Integer = Integer
    String = String
    Text = Text
    Float = Float
    Boolean = Boolean
    Date = Date
    Time = Time
    DateTime = DateTime
    Enum = Enum
    ForeignKey = ForeignKey
    Table = Table
    UniqueConstraint = UniqueConstraint
    CheckConstraint = CheckConstraint
    Index = Index
    relationship = relationship
    backref = backref
    func = func
    select = select

    def __init__(self, database_url: str):
        self.engine = create_engine(database_url, future=True)
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, autocommit=False, future=True)
        self.session = scoped_session(self.SessionLocal)
        Base.query = self.session.query_property()

    def remove_session(self) -> None:
        self.session.remove()

    def create_all(self) -> None:
        Base.metadata.create_all(self.engine)

    def drop_all(self) -> None:
        Base.metadata.drop_all(self.engine)

    def __getattr__(self, item: str) -> Any:
        return getattr(Base, item)


from app.config import settings

db = Database(settings.SQLALCHEMY_DATABASE_URI)
