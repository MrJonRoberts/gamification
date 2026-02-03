from datetime import datetime
from app.extensions import db
from app.security import hash_password, verify_password


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    student_code = db.Column(db.String(32), unique=True, nullable=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="student")  # student|issuer|admin
    password_hash = db.Column(db.String(255), nullable=False)
    registered_method = db.Column(db.String(20), nullable=False, default="site")  # site|bulk
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    avatar = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)


    issued_badges = db.relationship(
        "Badge",
        backref="creator",
        lazy=True,
        foreign_keys="Badge.created_by_id",
    )

    # All attendance rows where THIS user is the student
    attendances = db.relationship(
        "Attendance",
        foreign_keys="Attendance.student_id",
        back_populates="student",
        cascade="all, delete-orphan",
    )

    # All attendance rows THIS user marked as staff
    marked_attendances = db.relationship(
        "Attendance",
        foreign_keys="Attendance.marked_by_user_id",
        back_populates="marked_by",
    )

    def set_password(self, password: str):
        self.password_hash = hash_password(password)

    def check_password(self, password: str) -> bool:
        return verify_password(password, self.password_hash)

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def is_authenticated(self) -> bool:
        return True

    def __repr__(self):
        return f"<User id={self.id} {self.full_name} role={self.role}>"


user_roles = db.Table(
    "user_roles",
    db.Column("user_id", db.Integer, db.ForeignKey("users.id"), primary_key=True),
    db.Column("role_id", db.Integer, db.ForeignKey("roles.id"), primary_key=True),
)

user_groups = db.Table(
    "user_groups",
    db.Column("user_id", db.Integer, db.ForeignKey("users.id"), primary_key=True),
    db.Column("group_id", db.Integer, db.ForeignKey("groups.id"), primary_key=True),
)

class Role(db.Model):
    __tablename__ = "roles"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True, nullable=False)

class Group(db.Model):
    __tablename__ = "groups"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), unique=True, nullable=False)
