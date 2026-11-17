import os
from datetime import datetime, timezone

from alibabacloud_dm20151123 import models as dm_models
from alibabacloud_tea_openapi.exceptions import ServerException, ThrottlingException
from celery.utils.log import get_task_logger
from Tea.exceptions import TeaException, UnretryableException

from app.tasks import celery_app
from app.extensions import db
from app.models.job import Job
from app.models.job_allocation import JobAllocation
from app.models.recipient import Recipient
from app.models.sender import SenderAddress
from app.models.send_log import SendLog
from app.services.alibaba_client import get_client_for_account
from app.services.quota import remaining_quota_today
from app.services import redis_counters

logger = get_task_logger(__name__)

# See ALIBABA_INTEGRATION.md "Error code -> internal handling map".
INVALID_RECIPIENT_CODES = {
    "InvalidToAddress",
    "InvalidReceiverName.Malformed",
    "InvalidReceiver.NotFound",
    "InvalidToAddress.Spam",
}
SENDER_DISABLE_CODES = {
    "InvalidMailAddress.NotFound",
    "InvalidMailAddressStatus.Malformed",
    "InvalidIP.NotFound",
}
SENDER_COOLDOWN_CODES = {"InvalidSendMail.Spam"}

# A sender in one of these states can still be sent from; only "active"
# senders are picked as a re-route target (matches build_allocation_plan).
USABLE_SENDER_STATUSES = ("active", "warming_up")

TRANSIENT_MAX_RETRIES = 3
TRANSIENT_BACKOFF_SECONDS = 10  # 10s, 20s, 40s


def _now():
    return datetime.now(timezone.utc)


def _is_transient(exc) -> bool:
    """
    Network/timeout/throttling/5xx — worth retrying with backoff. Note the
    SDK wraps network failures in UnretryableException, which is itself a
    TeaException with no error code, so it has to be checked before any
    code-based handling.
    """
    return isinstance(
        exc, (UnretryableException, ThrottlingException, ServerException, OSError)
    )


def _describe(exc) -> str:
    """str(exc) that can't itself raise — some SDK exceptions have fragile __str__."""
    try:
        return str(exc) or type(exc).__name__
    except Exception:
        return type(exc).__name__


@celery_app.task(
    name="tasks.send_recipient",
    bind=True,
    rate_limit=f"{os.environ.get('SEND_RATE_LIMIT_PER_SECOND', '5')}/s",
)
def send_recipient(self, job_id, recipient_id, sender_id, allocation_id):
    job = db.session.get(Job, job_id)
    recipient = db.session.get(Recipient, recipient_id)
    sender = db.session.get(SenderAddress, sender_id)
    allocation = db.session.get(JobAllocation, allocation_id)

    if job is None or recipient is None or sender is None:
        logger.warning(
            "Skipping send_recipient: missing job=%s recipient=%s sender=%s",
            job_id, recipient_id, sender_id,
        )
        return

    if job.status not in ("queued", "sending"):
        # Job was paused/cancelled after this task was already enqueued —
        # let it no-op rather than send. `resume_job` re-dispatches
        # whatever's still missing a final send_log row.
        logger.info("Skipping send_recipient: job %s is %s", job.id, job.status)
        return

    already_sent = SendLog.query.filter_by(
        job_id=job.id, recipient_id=recipient.id, status="sent"
    ).first()
    if already_sent:
        # Redelivered task (worker crash with acks_late) or overlapping
        # resume — never email the same person twice for one job.
        logger.info("Skipping send_recipient: %s already sent for job %s", recipient.email_address, job.id)
        return

    tried_sender_ids = set()
    attempt = 1
    while True:
        tried_sender_ids.add(sender.id)

        if sender.status not in USABLE_SENDER_STATUSES:
            # Sender went into cooldown/disabled after this task was queued
            # (or between attempts). Don't touch it — move the recipient.
            moved = _reroute(job, sender, allocation, tried_sender_ids)
            if moved is None:
                _fail(
                    job, recipient, sender, allocation, attempt,
                    "NoSenderAvailable",
                    f"Sender {sender.email_address} is {sender.status} and no other "
                    f"active sender has quota left today.",
                )
                break
            sender, allocation = moved
            attempt += 1
            continue

        try:
            outcome, code, message = _send_once(job, recipient, sender, allocation, attempt)
        except Exception as exc:
            if _is_transient(exc):
                if self.request.retries < TRANSIENT_MAX_RETRIES:
                    # Nothing has been logged or counted for this attempt, so
                    # the retry can't double-count. Carry the *current*
                    # sender/allocation so a retry after a re-route doesn't
                    # re-route (and re-count) a second time.
                    raise self.retry(
                        exc=exc,
                        args=(job.id, recipient.id, sender.id, allocation.id if allocation else None),
                        countdown=TRANSIENT_BACKOFF_SECONDS * 2 ** self.request.retries,
                        max_retries=TRANSIENT_MAX_RETRIES,
                    )
                _fail(
                    job, recipient, sender, allocation, attempt,
                    type(exc).__name__,
                    f"Gave up after {TRANSIENT_MAX_RETRIES} retries: {_describe(exc)}",
                )
            else:
                logger.exception("Unexpected error sending to %s", recipient.email_address)
                _fail(job, recipient, sender, allocation, attempt, type(exc).__name__, _describe(exc))
            break

        if outcome == "sender_problem":
            # The sender itself is the problem (cooldown/disabled) — per the
            # spec, don't retry this recipient on the same sender; try another.
            moved = _reroute(job, sender, allocation, tried_sender_ids)
            if moved is None:
                _fail(job, recipient, sender, allocation, attempt, code, message)
                break
            sender, allocation = moved
            attempt += 1
            continue

        break  # "sent" or "failed" — already logged and counted

    _maybe_complete_job(job.id)


def _send_once(job, recipient, sender, allocation, attempt):
    """
    One send attempt. Returns (outcome, error_code, error_message) where
    outcome is "sent", "failed" (final, logged) or "sender_problem" (the
    attempt is logged as "retrying" and the caller re-routes). Raises on
    anything else so the caller can decide whether it is transient.
    """
    template = job.template
    subject = (job.subject_override or template.subject_default or "")[:100]

    request = dm_models.SingleSendMailRequest(
        account_name=sender.email_address,
        address_type=1,
        reply_to_address="true" if sender.reply_to_address else "false",
        subject=subject,
        to_address=recipient.email_address,
        html_body=template.html_body,
        text_body=template.text_body,
        from_alias=sender.from_alias,
        tag_name=f"job_{job.id}",
        reply_address=sender.reply_to_address,
        reply_address_alias=sender.reply_to_alias,
        un_subscribe_link_type="default",
        un_subscribe_filter_level="default",
    )

    try:
        client = get_client_for_account(sender.account)
        response = client.single_send_mail(request)
    except TeaException as exc:
        if _is_transient(exc):
            raise
        code = exc.code or type(exc).__name__
        message = exc.message or _describe(exc)

        if code in SENDER_COOLDOWN_CODES:
            sender.status = "cooldown"
            sender.last_cooldown_at = _now()
            sender.last_cooldown_reason = f"{code}: {message}"
            db.session.commit()
            _write_log(job, recipient, sender, "retrying", attempt, error_code=code, error_message=message)
            return "sender_problem", code, message

        if code in SENDER_DISABLE_CODES:
            sender.status = "disabled"
            db.session.commit()
            logger.error("Sender %s disabled due to %s: %s", sender.email_address, code, message)
            _write_log(job, recipient, sender, "retrying", attempt, error_code=code, error_message=message)
            return "sender_problem", code, message

        if code in INVALID_RECIPIENT_CODES:
            recipient.is_valid_format = 0
            db.session.commit()

        _fail(job, recipient, sender, allocation, attempt, code, message)
        return "failed", code, message

    body = response.body
    _write_log(
        job, recipient, sender, "sent", attempt,
        request_id=body.request_id, env_id=body.env_id,
    )
    _bump_counts(job, allocation, sent=1)
    return "sent", None, None


def _reroute(job, old_sender, old_allocation, tried_sender_ids):
    """
    Moves one recipient's slot from old_sender to the active sender with the
    most quota left today (skipping any already tried for this recipient).
    Returns (new_sender, new_allocation), or None if nobody has capacity —
    in which case the recipient is left unsent for a follow-up job.
    """
    candidates = [
        (sender, remaining_quota_today(sender))
        for sender in SenderAddress.query.filter_by(status="active").all()
        if sender.id not in tried_sender_ids
    ]
    candidates = [(s, quota) for s, quota in candidates if quota > 0]
    if not candidates:
        return None
    new_sender = max(candidates, key=lambda pair: pair[1])[0]

    new_allocation = JobAllocation.query.filter_by(job_id=job.id, sender_id=new_sender.id).first()
    if new_allocation is None:
        new_allocation = JobAllocation(job_id=job.id, sender_id=new_sender.id, allocated_count=0)
        db.session.add(new_allocation)
        db.session.flush()

    # Atomic, so concurrent workers re-routing at once can't lose an update.
    if old_allocation is not None:
        JobAllocation.query.filter_by(id=old_allocation.id).update(
            {JobAllocation.allocated_count: JobAllocation.allocated_count - 1}
        )
    JobAllocation.query.filter_by(id=new_allocation.id).update(
        {JobAllocation.allocated_count: JobAllocation.allocated_count + 1}
    )
    db.session.commit()
    db.session.refresh(new_allocation)

    logger.info(
        "Re-routed a job %s recipient from %s to %s",
        job.id, old_sender.email_address, new_sender.email_address,
    )
    return new_sender, new_allocation


def _fail(job, recipient, sender, allocation, attempt, error_code, error_message):
    _write_log(job, recipient, sender, "failed", attempt, error_code=error_code, error_message=error_message)
    _bump_counts(job, allocation, failed=1)


def _write_log(job, recipient, sender, status, attempt, request_id=None, env_id=None, error_code=None, error_message=None):
    db.session.add(
        SendLog(
            job_id=job.id,
            recipient_id=recipient.id,
            sender_id=sender.id,
            status=status,
            attempt_number=attempt,
            alibaba_request_id=request_id,
            alibaba_env_id=env_id,
            error_code=error_code,
            error_message=error_message,
        )
    )
    db.session.commit()


def _bump_counts(job, allocation, sent=0, failed=0):
    # Atomic SQL increments: several workers finish sends at the same time,
    # and a Python-side `job.sent_count += 1` would lose updates (and then
    # the job would never reach its total and never complete).
    Job.query.filter_by(id=job.id).update(
        {Job.sent_count: Job.sent_count + sent, Job.failed_count: Job.failed_count + failed}
    )
    if allocation is not None:
        JobAllocation.query.filter_by(id=allocation.id).update(
            {
                JobAllocation.sent_count: JobAllocation.sent_count + sent,
                JobAllocation.failed_count: JobAllocation.failed_count + failed,
            }
        )
    db.session.commit()

    if sent:
        redis_counters.increment(job.id, "sent", sent)
    if failed:
        redis_counters.increment(job.id, "failed", failed)


def _maybe_complete_job(job_id):
    """
    total_recipients is the number of recipients this job actually dispatched
    (the allocated total, not the whole list), so a partially-allocated job
    completes once everything it dispatched has a final result.
    """
    job = db.session.get(Job, job_id)
    db.session.refresh(job)
    processed = job.sent_count + job.failed_count
    if job.total_recipients <= 0 or processed < job.total_recipients:
        return

    threshold = int(os.environ.get("JOB_FAILURE_THRESHOLD_PERCENT", "5"))
    failure_rate = job.failed_count / job.total_recipients * 100
    final_status = "completed_with_errors" if failure_rate > threshold else "completed"

    # Conditional so two workers finishing simultaneously can't both finalize,
    # and so a job that was paused/cancelled meanwhile isn't overwritten.
    Job.query.filter(
        Job.id == job.id, Job.status.in_(("queued", "sending"))
    ).update({Job.status: final_status, Job.completed_at: _now()}, synchronize_session=False)
    db.session.commit()
