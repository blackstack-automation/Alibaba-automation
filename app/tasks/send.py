import os
from datetime import datetime, timezone

from alibabacloud_dm20151123 import models as dm_models
from celery.utils.log import get_task_logger
from Tea.exceptions import TeaException

from app.tasks import celery_app
from app.extensions import db
from app.models.job import Job
from app.models.job_allocation import JobAllocation
from app.models.recipient import Recipient
from app.models.sender import SenderAddress
from app.models.send_log import SendLog
from app.services.alibaba_client import get_client_for_account
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


def _now():
    return datetime.now(timezone.utc)


@celery_app.task(
    name="tasks.send_recipient",
    rate_limit=f"{os.environ.get('SEND_RATE_LIMIT_PER_SECOND', '5')}/s",
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def send_recipient(job_id, recipient_id, sender_id, allocation_id):
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
        # whatever's still missing a send_log row.
        logger.info("Skipping send_recipient: job %s is %s", job.id, job.status)
        return

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
        body = response.body
        _write_log(
            job, recipient, sender,
            status="sent", request_id=body.request_id, env_id=body.env_id,
        )
        _bump_counts(job, allocation, sent=1)
    except TeaException as exc:
        _handle_api_error(job, recipient, sender, allocation, exc)
    except Exception as exc:
        logger.exception("Unexpected error sending to %s", recipient.email_address)
        _write_log(job, recipient, sender, status="failed", error_message=str(exc))
        _bump_counts(job, allocation, failed=1)
        raise

    _maybe_complete_job(job)


def _handle_api_error(job, recipient, sender, allocation, exc: TeaException):
    code = exc.code or ""
    message = exc.message or ""

    if code in SENDER_COOLDOWN_CODES:
        sender.status = "cooldown"
        sender.last_cooldown_at = _now()
        sender.last_cooldown_reason = f"{code}: {message}"
        db.session.commit()
    elif code in SENDER_DISABLE_CODES:
        sender.status = "disabled"
        db.session.commit()
        logger.error("Sender %s disabled due to %s: %s", sender.email_address, code, message)
    elif code in INVALID_RECIPIENT_CODES:
        recipient.is_valid_format = 0
        db.session.commit()

    _write_log(job, recipient, sender, status="failed", error_code=code, error_message=message)
    _bump_counts(job, allocation, failed=1)


def _write_log(job, recipient, sender, status, request_id=None, env_id=None, error_code=None, error_message=None):
    db.session.add(
        SendLog(
            job_id=job.id,
            recipient_id=recipient.id,
            sender_id=sender.id,
            status=status,
            alibaba_request_id=request_id,
            alibaba_env_id=env_id,
            error_code=error_code,
            error_message=error_message,
        )
    )
    db.session.commit()


def _bump_counts(job, allocation, sent=0, failed=0):
    job.sent_count += sent
    job.failed_count += failed
    if allocation is not None:
        allocation.sent_count += sent
        allocation.failed_count += failed
    db.session.commit()

    if sent:
        redis_counters.increment(job.id, "sent", sent)
    if failed:
        redis_counters.increment(job.id, "failed", failed)


def _maybe_complete_job(job):
    processed = job.sent_count + job.failed_count
    if processed < job.total_recipients:
        return

    threshold = int(os.environ.get("JOB_FAILURE_THRESHOLD_PERCENT", "5"))
    failure_rate = (job.failed_count / job.total_recipients * 100) if job.total_recipients else 0
    job.status = "completed_with_errors" if failure_rate > threshold else "completed"
    job.completed_at = _now()
    db.session.commit()
