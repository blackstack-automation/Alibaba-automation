from datetime import datetime, timezone

from app.extensions import db


def _now():
    return datetime.now(timezone.utc)


class SendLog(db.Model):
    __tablename__ = "send_logs"

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    recipient_id = db.Column(db.Integer, db.ForeignKey("recipients.id"), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey("sender_addresses.id"), nullable=False)
    status = db.Column(db.String(20), nullable=False)  # 'sent' | 'failed' | 'retrying'
    alibaba_request_id = db.Column(db.String(255))
    alibaba_env_id = db.Column(db.String(255))
    error_code = db.Column(db.String(255))
    error_message = db.Column(db.Text)
    attempt_number = db.Column(db.Integer, nullable=False, default=1)
    sent_at = db.Column(db.DateTime, default=_now)

    recipient = db.relationship("Recipient")
    sender = db.relationship("SenderAddress")


db.Index("idx_send_logs_job", SendLog.job_id)
db.Index("idx_send_logs_sender_date", SendLog.sender_id, SendLog.sent_at)
db.Index("idx_send_logs_status", SendLog.status)
