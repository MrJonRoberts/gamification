from flask import Blueprint

attendance = Blueprint("attendance", __name__, template_folder="../../templates/attendance", static_folder="../../static")

from . import routes  # noqa