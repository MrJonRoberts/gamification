import os
from flask import Flask
from .config import Config
from .extensions import db, migrate, login_manager, csrf
from .models import User

def create_app():
    app = Flask(__name__, instance_relative_config=True, static_folder="static", template_folder="templates")
    app.config.from_object(Config)

    # Ensure instance folder exists
    os.makedirs(app.instance_path, exist_ok=True)

    # If using SQLite and the URI is relative (sqlite:///something.db), anchor it to the instance folder
    uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if uri.startswith("sqlite:///") and not uri.startswith("sqlite:////"):
        rel = uri.replace("sqlite:///", "", 1)
        if not os.path.isabs(rel):
            abs_path = os.path.join(app.instance_path, rel)
            # Normalize backslashes to forward slashes for SQLAlchemy/SQLite
            abs_path = abs_path.replace("\\", "/")
            app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{abs_path}"


    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)


    # Blueprints
    from .blueprints.main.routes import main_bp
    from .blueprints.auth.routes import auth_bp
    from .blueprints.students.routes import students_bp
    from .blueprints.courses.routes import courses_bp
    from .blueprints.badges.routes import badges_bp
    from .blueprints.awards.routes import awards_bp
    from .blueprints.points.routes import points_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(students_bp, url_prefix="/students")
    app.register_blueprint(courses_bp, url_prefix="/courses")
    app.register_blueprint(badges_bp, url_prefix="/badges")
    app.register_blueprint(awards_bp, url_prefix="/awards")
    app.register_blueprint(points_bp, url_prefix="/points")

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    @login_manager.unauthorized_handler
    def unauthorized():
        from flask import redirect, url_for
        return redirect(url_for("auth.login"))

    return app
