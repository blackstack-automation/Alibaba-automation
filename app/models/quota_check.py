from datetime import datetime, timezone

from app.extensions import db


def _now():
    return datetime.now(timezone.utc)


class QuotaCheck(db.Model):
    __tablename__ = "quota_checks"

    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(
        db.Integer, db.ForeignKey("sender_addresses.id", ondelete="CASCADE"), nullable=False
    )
    checked_at = db.Column(db.DateTime, default=_now)
    sent_today_count = db.Column(db.Integer, nullable=False, default=0)
    estimated_remaining = db.Column(db.Integer)
    source = db.Column(db.String(20), nullable=False, default="computed")  # 'computed'|'manual'|'api'
    note = db.Column(db.Text)


db.Index("idx_quota_checks_sender", QuotaCheck.sender_id, QuotaCheck.checked_at)
