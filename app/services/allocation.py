from app.models.sender import SenderAddress
from app.services.quota import remaining_quota_today


def build_allocation_plan(recipient_count: int) -> tuple[list[dict], int]:
    """
    Returns (plan, remaining) where plan is a list of {sender_id, sender, count}
    allocations that sum to at most recipient_count, and remaining is the
    unallocated count if total available quota is insufficient.
    """
    eligible_senders = SenderAddress.query.filter_by(status="active").all()
    senders_with_quota = [
        (sender, remaining_quota_today(sender)) for sender in eligible_senders
    ]
    senders_with_quota.sort(key=lambda pair: pair[1], reverse=True)

    plan = []
    remaining = recipient_count
    for sender, quota in senders_with_quota:
        if remaining <= 0:
            break
        take = min(quota, remaining)
        if take > 0:
            plan.append({"sender_id": sender.id, "sender": sender, "count": take})
            remaining -= take

    return plan, remaining
