from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import StringField, PasswordField, SelectField, TextAreaField, IntegerField, DateTimeLocalField
from wtforms.widgets import HiddenInput
from wtforms.validators import DataRequired, Optional, Length, NumberRange, Email


class AccountForm(FlaskForm):
    label = StringField("Label", validators=[DataRequired(), Length(max=255)])
    access_key_id = StringField("Access Key ID", validators=[DataRequired(), Length(max=255)])
    access_key_secret = PasswordField(
        "Access Key Secret", validators=[Optional(), Length(max=255)]
    )
    region_endpoint = SelectField(
        "Region endpoint",
        choices=[
            ("dm.aliyuncs.com", "dm.aliyuncs.com (default)"),
            ("dm.ap-southeast-1.aliyuncs.com", "dm.ap-southeast-1.aliyuncs.com"),
        ],
        default="dm.aliyuncs.com",
    )
    notes = TextAreaField("Notes", validators=[Optional(), Length(max=2000)])


class SenderForm(FlaskForm):
    email_address = StringField("Email address", validators=[DataRequired(), Email(), Length(max=255)])
    from_alias = StringField("From alias", validators=[Optional(), Length(max=15)])
    reply_to_address = StringField(
        "Reply-to address", validators=[Optional(), Email(), Length(max=255)]
    )
    reply_to_alias = StringField("Reply-to alias", validators=[Optional(), Length(max=255)])
    baseline_daily_quota = IntegerField(
        "Baseline daily quota", validators=[DataRequired(), NumberRange(min=0)], default=200
    )
    status = SelectField(
        "Status",
        choices=[
            ("active", "Active"),
            ("warming_up", "Warming up"),
            ("cooldown", "Cooldown"),
            ("disabled", "Disabled"),
        ],
        default="active",
    )


class TemplateForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired(), Length(max=255)])
    description = TextAreaField("Description", validators=[Optional(), Length(max=2000)])
    subject_default = StringField(
        "Default subject", validators=[Optional(), Length(max=100)]
    )
    html_file = FileField("Upload .html file", validators=[Optional(), FileAllowed(["html", "htm"])])
    html_paste = TextAreaField("Paste HTML", validators=[Optional()])
    text_body = TextAreaField("Plaintext body (optional)", validators=[Optional()])


class JobForm(FlaskForm):
    name = StringField("Job name", validators=[DataRequired(), Length(max=255)])
    template_id = SelectField("Template", coerce=int, validators=[DataRequired()])
    recipient_list_id = SelectField("Recipient list", coerce=int, validators=[DataRequired()])
    subject_override = StringField("Subject", validators=[Optional(), Length(max=100)])
    schedule_choice = SelectField(
        "Schedule",
        choices=[("now", "Send immediately"), ("later", "Schedule for later")],
        default="now",
    )
    scheduled_at = DateTimeLocalField(
        "Scheduled for", validators=[Optional()], format="%Y-%m-%dT%H:%M"
    )
    # Set (hidden) when this job is a follow-up to an earlier one.
    parent_job_id = IntegerField(widget=HiddenInput(), validators=[Optional()])
