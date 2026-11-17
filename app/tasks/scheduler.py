from datetime import datetime, timezone

from celery.utils.log import get_task_logger

from app.tasks import celery_app
from app.extensions import db
from app.models.job import Job
from app.models.sender import SenderAddress

logger = get_task_logger(__name__)


@celery_app.task(name="tasks.review_sender_health")
def review_sender_health():
    """
    Daily Beat task per ALIBABA_INTEGRATION.md: Alibaba's limits are
    daily-rolling, so a sender in cooldown yesterday should get another
    chance today. Quota-adjustment suggestions are deliberately NOT
    computed/applied here — they're derived live from send_logs on the
    dashboard (see services/quota.compute_quota_suggestions) so there's
    one source of truth instead of a second copy that can go stale.
    """
    cooled_down = SenderAddress.query.filter_by(status="cooldown").all()
    for sender in cooled_down:
        sender.status = "active"
        logger.info("Reset sender %s from cooldown to active", sender.email_address)
    db.session.commit()
    return len(cooled_down)


@celery_app.task(name="tasks.poll_pending_jobs")
def poll_pending_jobs():
    """
    Beat task (every minute) — fires jobs whose scheduled_at has arrived.
    Immediate ("send now") jobs are dispatched directly at creation time
    in routes/jobs.py; this task is specifically for the "Schedule for
    later" path.
    """
    from app.tasks.dispatch import dispatch_job

    now = datetime.now(timezone.utc)
    due_jobs = Job.query.filter(
        Job.status == "pending",
        Job.scheduled_at.isnot(None),
        Job.scheduled_at <= now,
    ).all()

    for job in due_jobs:
        try:
            dispatch_job.delay(job.id)
            job.status = "queued"
        except Exception:
            logger.exception("Could not dispatch scheduled job %s", job.id)
    db.session.commit()

    return len(due_jobs)
