# app/blueprints/badges/forms.py
from flask_wtf import FlaskForm
from flask_wtf.file import FileField
from wtforms import StringField, IntegerField, TextAreaField
from wtforms.validators import DataRequired, Length, NumberRange, Optional

class BadgeForm(FlaskForm):
    name = StringField(
        "Name",
        validators=[DataRequired(), Length(max=120)]
    )
    description = TextAreaField(
        "Description",
        validators=[Optional(), Length(max=1000)]
    )
    points = IntegerField(
        "Points",
        default=0,
        validators=[Optional(), NumberRange(min=0, message="Points must be 0 or greater")]
    )
    icon = FileField(
        "Icon (optional)",
        validators=[Optional()]  # extension/validity is enforced in services.images + route
    )
