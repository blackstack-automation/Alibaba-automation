from datetime import date

from flask import Blueprint, render_template
from flask_login import login_required

from app.extensions import db
from app.models.sender import SenderAddress
from app.models.send_log import SendLog
from app.models.job import Job
from app.services.quota import sent_today_count, compute_quota_suggestions

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
@login_required
def index():
    senders = SenderAddress.query.join(SenderAddress.account).order_by(
        SenderAddress.email_address
    ).all()

    sender_rows = []
    for sender in senders:
        sent_today = sent_today_count(sender.id)
        sender_rows.append(
            {
                "sender": sender,
                "sent_today": sent_today,
                "remaining": max(sender.baseline_daily_quota - sent_today, 0),
            }
        )

    today_str = date.today().isoformat()
    sent_today_total = (
        db.session.query(SendLog)
        .filter(SendLog.status == "sent")
        .filter(db.func.strftime("%Y-%m-%d", SendLog.sent_at) == today_str)
        .count()
    )
    failed_today_total = (
        db.session.query(SendLog)
        .filter(SendLog.status == "failed")
        .filter(db.func.strftime("%Y-%m-%d", SendLog.sent_at) == today_str)
        .count()
    )
    attempted = sent_today_total + failed_today_total
    success_rate = round((sent_today_total / attempted) * 100, 1) if attempted else None

    active_jobs = Job.query.filter(Job.status.in_(("queued", "sending"))).all()
    quota_suggestions = compute_quota_suggestions()

    return render_template(
        "dashboard/index.html",
        sender_rows=sender_rows,
        sent_today_total=sent_today_total,
        failed_today_total=failed_today_total,
        success_rate=success_rate,
        active_jobs=active_jobs,
        quota_suggestions=quota_suggestions,
    )


@dashboard_bp.route("/healthz")
def healthz():
    return {"status": "ok"}, 200
