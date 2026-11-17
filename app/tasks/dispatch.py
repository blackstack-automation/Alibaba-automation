from datetime import datetime, timezone

from app.tasks import celery_app
from app.extensions import db
from app.models.job import Job
from app.models.job_allocation import JobAllocation
from app.models.recipient import Recipient
from app.models.send_log import SendLog


@celery_app.task(name="tasks.dispatch_job")
def dispatch_job(job_id):
    from app.tasks.send import send_recipient

    job = db.session.get(Job, job_id)
    if job is None or job.status not in ("pending", "queued"):
        return

    job.status = "sending"
    job.started_at = datetime.now(timezone.utc)
    db.session.commit()

    allocations = JobAllocation.query.filter_by(job_id=job.id).all()
    recipients = (
        Recipient.query.filter_by(list_id=job.recipient_list_id, is_valid_format=1)
        .order_by(Recipient.id)
        .all()
    )

    recipient_iter = iter(recipients)
    dispatched = 0
    for allocation in allocations:
        for _ in range(allocation.allocated_count):
            recipient = next(recipient_iter, None)
            if recipient is None:
                break
            send_recipient.delay(job.id, recipient.id, allocation.sender_id, allocation.id)
            dispatched += 1

    if dispatched == 0:
        job.status = "failed"
        db.session.commit()


@celery_app.task(name="tasks.resume_job")
def resume_job(job_id):
    """
    Re-dispatches send_recipient for whatever this job hasn't attempted
    yet — used both for the Resume button (after a Pause) and, per
    SETUP.md's runbook, for manually recovering a job after a crashed
    worker.
    """
    from app.tasks.send import send_recipient

    job = db.session.get(Job, job_id)
    if job is None:
        return

    # Only final results count. A "retrying" row is an attempt that was
    # re-routed to another sender, so that recipient may still be outstanding.
    already_attempted = {
        row.recipient_id
        for row in SendLog.query.filter(
            SendLog.job_id == job.id, SendLog.status.in_(("sent", "failed"))
        ).all()
    }
    recipients = (
        Recipient.query.filter_by(list_id=job.recipient_list_id, is_valid_format=1)
        .order_by(Recipient.id)
        .all()
    )
    remaining = [r for r in recipients if r.id not in already_attempted]

    job.status = "sending"
    db.session.commit()

    remaining_iter = iter(remaining)
    allocations = JobAllocation.query.filter_by(job_id=job.id).all()
    for allocation in allocations:
        capacity = allocation.allocated_count - allocation.sent_count - allocation.failed_count
        for _ in range(max(capacity, 0)):
            recipient = next(remaining_iter, None)
            if recipient is None:
                break
            send_recipient.delay(job.id, recipient.id, allocation.sender_id, allocation.id)
