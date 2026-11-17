from datetime import datetime, timezone

from app.extensions import db


def _now():
    return datetime.now(timezone.utc)


class RecipientList(db.Model):
    __tablename__ = "recipient_lists"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    source_filename = db.Column(db.String(255))
    total_count = db.Column(db.Integer, nullable=False, default=0)
    valid_count = db.Column(db.Integer, nullable=False, default=0)
    duplicate_count = db.Column(db.Integer, nullable=False, default=0)
    invalid_count = db.Column(db.Integer, nullable=False, default=0)
    uploaded_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=_now)

    recipients = db.relationship(
        "Recipient", backref="recipient_list", cascade="all, delete-orphan", lazy="dynamic"
    )


class Recipient(db.Model):
    __tablename__ = "recipients"

    id = db.Column(db.Integer, primary_key=True)
    list_id = db.Column(
        db.Integer, db.ForeignKey("recipient_lists.id", ondelete="CASCADE"), nullable=False
    )
    email_address = db.Column(db.String(255), nullable=False)
    first_name = db.Column(db.String(255))
    last_name = db.Column(db.String(255))
    custom_fields = db.Column(db.Text)  # JSON blob
    is_valid_format = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.DateTime, default=_now)
