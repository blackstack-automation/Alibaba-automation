import csv
import io
import json
import time
from datetime import datetime, timezone

from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, Response, current_app
from flask_login import login_required, current_user

from app.extensions import db
from app.forms import JobForm
from app.models.job import Job
from app.models.job_allocation import JobAllocation
from app.models.template import EmailTemplate
from app.models.recipient import RecipientList
from app.models.send_log import SendLog
from app.services.allocation import build_allocation_plan
from app.services import redis_counters

TERMINAL_STATUSES = ("completed", "completed_with_errors", "failed", "cancelled")

jobs_bp = Blueprint("jobs", __name__)


def _try_dispatch(job):
    """Enqueues the dispatch task; degrades gracefully if Celery/Redis isn't reachable."""
    try:
        from app.tasks.dispatch import dispatch_job

        dispatch_job.delay(job.id)
        job.status = "queued"
        db.session.commit()
    except Exception as exc:
        flash(
            f"Job saved as 'pending' but could not be queued for sending "
            f"(Celery/Redis unavailable: {exc}). Use 'Send Now' once your worker is running.",
            "warning",
        )


def _populate_choices(form):
    form.template_id.choices = [
        (t.id, t.name) for t in EmailTemplate.query.order_by(EmailTemplate.name).all()
    ]
    form.recipient_list_id.choices = [
        (rl.id, f"{rl.name} ({rl.valid_count} valid)")
        for rl in RecipientList.query.order_by(RecipientList.name).all()
    ]


@jobs_bp.route("/")
@login_required
def list_jobs():
    jobs = Job.query.order_by(Job.created_at.desc()).all()
    return render_template("jobs/list.html", jobs=jobs)


@jobs_bp.route("/preview-allocation", methods=["POST"])
@login_required
def preview_allocation():
    recipient_list = db.get_or_404(RecipientList, request.form.get("recipient_list_id", type=int))
    plan, remaining = build_allocation_plan(recipient_list.valid_count)
    return jsonify(
        {
            "total": recipient_list.valid_count,
            "remaining": remaining,
            "plan": [
                {"sender_email": item["sender"].email_address, "count": item["count"]}
                for item in plan
            ],
        }
    )


@jobs_bp.route("/new", methods=["GET", "POST"])
@login_required
def new_job():
    form = JobForm()
    _populate_choices(form)

    if not form.template_id.choices:
        flash("Upload a template before creating a job.", "error")
        return redirect(url_for("mail_templates.list_templates"))
    if not form.recipient_list_id.choices:
        flash("Upload a recipient list before creating a job.", "error")
        return redirect(url_for("recipients.list_recipients"))

    if form.validate_on_submit():
        if form.schedule_choice.data == "later" and not form.scheduled_at.data:
            form.scheduled_at.errors.append("Choose a date/time for a scheduled job.")
        else:
            recipient_list = db.get_or_404(RecipientList, form.recipient_list_id.data)
            plan, remaining = build_allocation_plan(recipient_list.valid_count)

            job = Job(
                name=form.name.data.strip(),
                template_id=form.template_id.data,
                recipient_list_id=form.recipient_list_id.data,
                subject_override=form.subject_override.data or None,
                status="pending",
                scheduled_at=form.scheduled_at.data if form.schedule_choice.data == "later" else None,
                total_recipients=recipient_list.valid_count,
                created_by=current_user.id,
            )
            db.session.add(job)
            db.session.flush()

            for item in plan:
                db.session.add(
                    JobAllocation(
                        job_id=job.id,
                        sender_id=item["sender_id"],
                        allocated_count=item["count"],
                    )
                )
            db.session.commit()

            if remaining > 0:
                flash(
                    f"Job '{job.name}' created, but only {job.total_recipients - remaining} of "
                    f"{job.total_recipients} recipients could be allocated given current quota. "
                    f"{remaining} will need a follow-up job.",
                    "warning",
                )
            else:
                flash(f"Job '{job.name}' created.", "success")

            if job.scheduled_at is None and plan:
                _try_dispatch(job)

            return redirect(url_for("jobs.view_job", job_id=job.id))

    template_subjects = {
        t.id: (t.subject_default or "") for t in EmailTemplate.query.all()
    }
    return render_template("jobs/form.html", form=form, template_subjects=template_subjects)


@jobs_bp.route("/<int:job_id>")
@login_required
def view_job(job_id):
    job = db.get_or_404(Job, job_id)
    allocations = JobAllocation.query.filter_by(job_id=job.id).all()
    failed_logs = (
        SendLog.query.filter_by(job_id=job.id, status="failed")
        .order_by(SendLog.sent_at.desc())
        .limit(50)
        .all()
    )
    return render_template(
        "jobs/detail.html", job=job, allocations=allocations, failed_logs=failed_logs
    )


@jobs_bp.route("/<int:job_id>/status")
@login_required
def status_stream(job_id):
    app = current_app._get_current_object()

    def generate():
        while True:
            with app.app_context():
                job = db.session.get(Job, job_id)
                if job is None:
                    yield "event: error\ndata: not found\n\n"
                    return

                live = redis_counters.read_counters(job_id)
                sent = live["sent"] if live else job.sent_count
                failed = live["failed"] if live else job.failed_count
                status = job.status
                total = job.total_recipients
                db.session.expire(job)

            payload = {"sent": sent, "failed": failed, "total": total, "status": status}
            yield f"data: {json.dumps(payload)}\n\n"

            if status in TERMINAL_STATUSES:
                return
            time.sleep(2)

    return Response(generate(), mimetype="text/event-stream")


@jobs_bp.route("/<int:job_id>/pause", methods=["POST"])
@login_required
def pause_job(job_id):
    job = db.get_or_404(Job, job_id)
    if job.status != "sending":
        flash(f"Job is '{job.status}' — can only pause a job that's sending.", "error")
    else:
        job.status = "paused"
        db.session.commit()
        flash(f"Job '{job.name}' paused. In-flight sends will finish; no new ones will start.", "success")
    return redirect(url_for("jobs.view_job", job_id=job.id))


@jobs_bp.route("/<int:job_id>/resume", methods=["POST"])
@login_required
def resume_job_route(job_id):
    job = db.get_or_404(Job, job_id)
    if job.status != "paused":
        flash(f"Job is '{job.status}' — can only resume a paused job.", "error")
        return redirect(url_for("jobs.view_job", job_id=job.id))

    try:
        from app.tasks.dispatch import resume_job

        resume_job.delay(job.id)
        flash(f"Job '{job.name}' resumed.", "success")
    except Exception as exc:
        flash(f"Could not resume (Celery/Redis unavailable: {exc}).", "warning")
    return redirect(url_for("jobs.view_job", job_id=job.id))


@jobs_bp.route("/<int:job_id>/cancel", methods=["POST"])
@login_required
def cancel_job(job_id):
    job = db.get_or_404(Job, job_id)
    if job.status in TERMINAL_STATUSES:
        flash(f"Job is already '{job.status}'.", "error")
    else:
        job.status = "cancelled"
        job.completed_at = datetime.now(timezone.utc)
        db.session.commit()
        flash(f"Job '{job.name}' cancelled. Any already-queued sends will skip themselves.", "success")
    return redirect(url_for("jobs.view_job", job_id=job.id))


@jobs_bp.route("/<int:job_id>/export-failed")
@login_required
def export_failed(job_id):
    job = db.get_or_404(Job, job_id)
    logs = (
        db.session.query(SendLog)
        .filter_by(job_id=job.id, status="failed")
        .order_by(SendLog.sent_at)
        .all()
    )

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["email", "sender", "error_code", "error_message", "sent_at"])
    for log in logs:
        writer.writerow(
            [
                log.recipient.email_address if log.recipient else "",
                log.sender.email_address if log.sender else "",
                log.error_code or "",
                log.error_message or "",
                log.sent_at.isoformat() if log.sent_at else "",
            ]
        )

    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="job-{job.id}-failed.csv"'},
    )


@jobs_bp.route("/<int:job_id>/send-now", methods=["POST"])
@login_required
def send_now(job_id):
    job = db.get_or_404(Job, job_id)
    if job.status not in ("pending",):
        flash(f"Job is '{job.status}', not pending — nothing to do.", "error")
        return redirect(url_for("jobs.view_job", job_id=job.id))

    _try_dispatch(job)
    if job.status == "queued":
        flash(f"Job '{job.name}' queued for sending.", "success")
    return redirect(url_for("jobs.view_job", job_id=job.id))
