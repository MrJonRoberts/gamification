from .routes import admin_bp  # noqa: F401

from flask import Blueprint
from flask_login import current_user
from functools import wraps
from flask import abort

# admin_bp = Blueprint("admin", __name__, url_prefix="/admin", template_folder="../../templates/admin")


