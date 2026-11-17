from datetime import datetime, timezone

from app.extensions import db


def _now():
    return datetime.now(timezone.utc)


class Account(db.Model):
    __tablename__ = "accounts"

    id = db.Column(db.Integer, primary_key=True)
    label = db.Column(db.String(255), nullable=False)
    access_key_id = db.Column(db.String(255), nullable=False)
    access_key_secret_encrypted = db.Column(db.Text, nullable=False)
    region_endpoint = db.Column(db.String(255), nullable=False, default="dm.aliyuncs.com")
    status = db.Column(db.String(20), nullable=False, default="active")  # 'active' | 'disabled'
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=_now)
    updated_at = db.Column(db.DateTime, default=_now, onupdate=_now)

    senders = db.relationship(
        "SenderAddress", backref="account", cascade="all, delete-orphan", lazy="dynamic"
    )
