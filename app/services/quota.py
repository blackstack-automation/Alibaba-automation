from datetime import date, datetime, timedelta, timezone

from app.extensions import db
from app.models.send_log import SendLog
from app.models.sender import SenderAddress

COOLDOWN_ERROR_CODE = "InvalidSendMail.Spam"
TRAILING_WINDOW_DAYS = 7
RAISE_THRESHOLD_UTILIZATION = 0.8
LOWER_THRESHOLD_COOLDOWN_COUNT = 2


def sent_today_count(sender_id: int) -> int:
    today_str = date.today().isoformat()
    return (
        db.session.query(SendLog)
        .filter(SendLog.sender_id == sender_id)
        .filter(SendLog.status == "sent")
        .filter(db.func.strftime("%Y-%m-%d", SendLog.sent_at) == today_str)
        .count()
    )


def remaining_quota_today(sender) -> int:
    used = sent_today_count(sender.id)
    return max(sender.baseline_daily_quota - used, 0)


def compute_quota_suggestions() -> list[dict]:
    """
    Advisory-only quota suggestions per ALIBABA_INTEGRATION.md's warm-up
    guidance — computed live from send_logs rather than stored, so
    there's never a stale copy to reconcile. Never auto-applied; the
    dashboard just displays these as dismissible notices.
    """
    since = datetime.now(timezone.utc) - timedelta(days=TRAILING_WINDOW_DAYS)
    suggestions = []

    senders = SenderAddress.query.filter(
        SenderAddress.status.in_(("active", "warming_up"))
    ).all()

    for sender in senders:
        cooldown_count = (
            db.session.query(SendLog)
            .filter(
                SendLog.sender_id == sender.id,
                SendLog.error_code == COOLDOWN_ERROR_CODE,
                SendLog.sent_at >= since,
            )
            .count()
        )
        sent_count = (
            db.session.query(SendLog)
            .filter(
                SendLog.sender_id == sender.id,
                SendLog.status == "sent",
                SendLog.sent_at >= since,
            )
            .count()
        )

        if cooldown_count > LOWER_THRESHOLD_COOLDOWN_COUNT:
            suggestions.append(
                {
                    "sender": sender,
                    "direction": "lower",
                    "message": (
                        f"{sender.email_address} hit cooldown {cooldown_count} times in the last "
                        f"{TRAILING_WINDOW_DAYS} days — consider lowering its baseline quota "
                        f"(currently {sender.baseline_daily_quota}/day)."
                    ),
                }
            )
        elif cooldown_count == 0 and sender.baseline_daily_quota > 0:
            avg_daily = sent_count / TRAILING_WINDOW_DAYS
            utilization = avg_daily / sender.baseline_daily_quota
            if utilization > RAISE_THRESHOLD_UTILIZATION:
                suggestions.append(
                    {
                        "sender": sender,
                        "direction": "raise",
                        "message": (
                            f"{sender.email_address} has used over "
                            f"{int(RAISE_THRESHOLD_UTILIZATION * 100)}% of its quota with a clean "
                            f"delivery record over the last {TRAILING_WINDOW_DAYS} days — consider "
                            f"raising its baseline quota (currently {sender.baseline_daily_quota}/day)."
                        ),
                    }
                )

    return suggestions
