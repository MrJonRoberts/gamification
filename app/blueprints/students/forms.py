# app/blueprints/students/forms.py
from flask_wtf import FlaskForm
from flask_wtf.file import FileField
from wtforms import StringField
from wtforms.validators import DataRequired, Email, Length, Optional

class StudentForm(FlaskForm):
    # Student code is optional in routes; make it Optional here.
    student_code = StringField(
        "Student Code",
        validators=[Optional(), Length(max=32)],
    )

    email = StringField(
        "Email",
        validators=[DataRequired(), Email(), Length(max=255)],
    )

    first_name = StringField(
        "First Name",
        validators=[DataRequired(), Length(max=100)],
    )

    last_name = StringField(
        "Last Name",
        validators=[DataRequired(), Length(max=100)],
    )

    # Optional photo upload (routes validate/resize via services.images)
    image = FileField("Photo", validators=[Optional()])
