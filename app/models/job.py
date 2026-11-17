from datetime import datetime, timezone

from app.extensions import db


def _now():
    return datetime.now(timezone.utc)


JOB_STATUSES = (
    "pending",
    "queued",
    "sending",
    "paused",
    "completed",
    "completed_with_errors",
    "failed",
    "cancelled",
)


class Job(db.Model):
    __tablename__ = "jobs"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    template_id = db.Column(db.Integer, db.ForeignKey("templates.id"), nullable=False)
    recipient_list_id = db.Column(db.Integer, db.ForeignKey("recipient_lists.id"), nullable=False)
    subject_override = db.Column(db.String(255))
    status = db.Column(db.String(30), nullable=False, default="pending")
    scheduled_at = db.Column(db.DateTime)
    started_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    total_recipients = db.Column(db.Integer, nullable=False, default=0)
    sent_count = db.Column(db.Integer, nullable=False, default=0)
    failed_count = db.Column(db.Integer, nullable=False, default=0)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    # Set when this job continues an earlier job on the same list (a follow-up).
    parent_job_id = db.Column(db.Integer, db.ForeignKey("jobs.id"))
    created_at = db.Column(db.DateTime, default=_now)
    updated_at = db.Column(db.DateTime, default=_now, onupdate=_now)

    template = db.relationship("EmailTemplate")
    recipient_list = db.relationship("RecipientList")
    allocations = db.relationship(
        "JobAllocation", backref="job", cascade="all, delete-orphan", lazy="dynamic"
    )


db.Index("idx_jobs_parent", Job.parent_job_id)
