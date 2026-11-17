from datetime import datetime, timezone

from app.extensions import db


def _now():
    return datetime.now(timezone.utc)


SENDER_STATUSES = ("active", "cooldown", "warming_up", "disabled")


class SenderAddress(db.Model):
    __tablename__ = "sender_addresses"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(
        db.Integer, db.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    email_address = db.Column(db.String(255), nullable=False)
    from_alias = db.Column(db.String(15))
    reply_to_address = db.Column(db.String(255))
    reply_to_alias = db.Column(db.String(255))
    status = db.Column(db.String(20), nullable=False, default="active")
    baseline_daily_quota = db.Column(db.Integer, nullable=False, default=200)
    warmup_started_at = db.Column(db.DateTime)
    last_cooldown_at = db.Column(db.DateTime)
    last_cooldown_reason = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=_now)
    updated_at = db.Column(db.DateTime, default=_now, onupdate=_now)

    __table_args__ = (db.UniqueConstraint("account_id", "email_address"),)
