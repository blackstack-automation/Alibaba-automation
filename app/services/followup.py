"""
Overflow protection: follow-up jobs.

A job that couldn't cover its whole list (quota ran out, cancelled, ...) can be
continued by a *follow-up* job. Jobs linked by ``parent_job_id`` form a "family";
a family member never re-emails a recipient another member already handled.

A brand-new job (no parent) is its own family, so it goes to everyone on its
list. That is deliberate: a different campaign must reach the whole list again.
"""
from sqlalchemy import select

from app.extensions import db
from app.models.job import Job
from app.models.job_allocation import JobAllocation
from app.models.recipient import Recipient
from app.models.send_log import SendLog
from app.services.allocation import build_allocation_plan

TERMINAL_STATUSES = ("completed", "completed_with_errors", "failed", "cancelled")
ACTIVE_STATUSES = ("pending", "queued", "sending", "paused")
# Failed recipients count as handled so a follow-up doesn't burn quota
# re-sending to addresses that already bounced. They stay in the failed CSV.
HANDLED_LOG_STATUSES = ("sent", "failed")


def family_job_ids(job) -> set[int]:
    """Every job linked to `job` through parent_job_id (ancestors, descendants, siblings)."""
    root = job
    while root.parent_job_id is not None:
        root = db.session.get(Job, root.parent_job_id)

    ids = {root.id}
    frontier = [root.id]
    while frontier:
        children = [
            row[0]
            for row in db.session.query(Job.id).filter(Job.parent_job_id.in_(frontier)).all()
        ]
        frontier = [child for child in children if child not in ids]
        ids.update(frontier)
    ids.add(job.id)
    return ids


def eligible_query(job):
    """Valid recipients on the job's list that nobody in its family has handled yet."""
    handled = select(SendLog.recipient_id).where(
        SendLog.job_id.in_(family_job_ids(job)),
        SendLog.status.in_(HANDLED_LOG_STATUSES),
    )
    return Recipient.query.filter(
        Recipient.list_id == job.recipient_list_id,
        Recipient.is_valid_format == 1,
        Recipient.id.not_in(handled),
    )


def eligible_count(job) -> int:
    return eligible_query(job).count()


def rebuild_allocations(job):
    """
    (Re)plans which senders cover this job, from today's live quota, and stores
    the plan. Replaces any earlier plan, so a job scheduled for later is planned
    when it actually runs rather than against whatever quota was left when it
    was created. Returns (eligible, allocated_total, remaining).
    """
    eligible = eligible_count(job)
    plan, remaining = build_allocation_plan(eligible)

    JobAllocation.query.filter_by(job_id=job.id).delete()
    for item in plan:
        db.session.add(
            JobAllocation(job_id=job.id, sender_id=item["sender_id"], allocated_count=item["count"])
        )
    job.total_recipients = sum(item["count"] for item in plan)
    return eligible, job.total_recipients, remaining


def followup_blocker(job):
    """Why a follow-up can't be created from `job` right now, or None if it can."""
    if job.status not in TERMINAL_STATUSES:
        return f"This job is still '{job.status}'. Wait for it to finish (or cancel it) first."
    family = family_job_ids(job)
    busy = Job.query.filter(Job.id.in_(family), Job.status.in_(ACTIVE_STATUSES)).first()
    if busy is not None:
        return (
            f"Related job '{busy.name}' is still '{busy.status}'. "
            "Wait for it to finish so nobody is emailed twice."
        )
    if eligible_count(job) == 0:
        return "Everyone on this list has already been handled — nothing left to send."
    return None
