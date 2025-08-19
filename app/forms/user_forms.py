from flask_wtf import FlaskForm
from wtforms import StringField, BooleanField, SelectMultipleField, SubmitField, SelectField
from wtforms.validators import DataRequired, Email, Optional, Length

class UserEditForm(FlaskForm):
    first_name = StringField("First name", validators=[DataRequired(), Length(max=120)])
    last_name  = StringField("Last name", validators=[DataRequired(), Length(max=120)])
    email      = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    student_code = StringField("Student code", validators=[Optional(), Length(max=64)])
    is_active  = BooleanField("Active")
    registration_method = SelectField(
        "Registration method",
        choices=[("site","site"),("bulk","bulk")],
        validators=[DataRequired()]
    )
    roles  = SelectMultipleField("Roles", coerce=int)
    groups = SelectMultipleField("Groups", coerce=int)
    submit = SubmitField("Save")
