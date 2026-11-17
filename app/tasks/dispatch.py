from datetime import datetime, timezone

from app.tasks import celery_app
from app.extensions import db
from app.models.job import Job
from app.models.job_allocation import JobAllocation
from app.models.recipient import Recipient
from app.services.followup import eligible_query, rebuild_allocations


@celery_app.task(name="tasks.dispatch_job")
def dispatch_job(job_id):
    from app.tasks.send import send_recipient

    job = db.session.get(Job, job_id)
    if job is None or job.status not in ("pending", "queued"):
        return

    job.status = "sending"
    job.started_at = datetime.now(timezone.utc)
    # Plan from the quota available *now*. The plan stored when the job was
    # created is only a preview: a job scheduled for tomorrow would otherwise
    # be sized against whatever quota was left today.
    rebuild_allocations(job)
    db.session.commit()

    allocations = JobAllocation.query.filter_by(job_id=job.id).all()
    # Skips anyone already emailed by a job this one is a follow-up to.
    recipients = (
        eligible_query(job).order_by(Recipient.id).limit(job.total_recipients).all()
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

    if dispatched != job.total_recipients:
        job.total_recipients = dispatched
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

    # eligible_query already leaves out every recipient with a final ("sent" or
    # "failed") log in this job's family, this job included. A "retrying" row is
    # an attempt that was re-routed to another sender, so that recipient may
    # still be outstanding and stays eligible.
    remaining = eligible_query(job).order_by(Recipient.id).all()

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
