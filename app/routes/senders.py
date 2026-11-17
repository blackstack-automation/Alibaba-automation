from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required

from app.extensions import db
from app.forms import SenderForm
from app.models.account import Account
from app.models.sender import SenderAddress
from app.services.quota import sent_today_count

senders_bp = Blueprint("senders", __name__)


@senders_bp.route("/accounts/<int:account_id>/senders")
@login_required
def list_senders(account_id):
    account = db.get_or_404(Account, account_id)
    senders = SenderAddress.query.filter_by(account_id=account.id).order_by(
        SenderAddress.created_at.desc()
    ).all()
    sent_today_by_id = {sender.id: sent_today_count(sender.id) for sender in senders}
    return render_template(
        "senders/list.html", account=account, senders=senders, sent_today_by_id=sent_today_by_id
    )


@senders_bp.route("/accounts/<int:account_id>/senders/new", methods=["GET", "POST"])
@login_required
def new_sender(account_id):
    account = db.get_or_404(Account, account_id)
    form = SenderForm()
    if form.validate_on_submit():
        sender = SenderAddress(
            account_id=account.id,
            email_address=form.email_address.data.strip(),
            from_alias=form.from_alias.data.strip() if form.from_alias.data else None,
            reply_to_address=form.reply_to_address.data.strip() if form.reply_to_address.data else None,
            reply_to_alias=form.reply_to_alias.data.strip() if form.reply_to_alias.data else None,
            baseline_daily_quota=form.baseline_daily_quota.data,
            status=form.status.data,
        )
        db.session.add(sender)
        db.session.commit()
        flash(f"Sender '{sender.email_address}' added.", "success")
        return redirect(url_for("senders.list_senders", account_id=account.id))

    return render_template("senders/form.html", form=form, account=account, sender=None)


@senders_bp.route("/senders/<int:sender_id>/edit", methods=["GET", "POST"])
@login_required
def edit_sender(sender_id):
    sender = db.get_or_404(SenderAddress, sender_id)
    account = sender.account
    form = SenderForm(obj=sender)

    if form.validate_on_submit():
        sender.email_address = form.email_address.data.strip()
        sender.from_alias = form.from_alias.data.strip() if form.from_alias.data else None
        sender.reply_to_address = (
            form.reply_to_address.data.strip() if form.reply_to_address.data else None
        )
        sender.reply_to_alias = (
            form.reply_to_alias.data.strip() if form.reply_to_alias.data else None
        )
        sender.baseline_daily_quota = form.baseline_daily_quota.data
        sender.status = form.status.data
        db.session.commit()
        flash(f"Sender '{sender.email_address}' updated.", "success")
        return redirect(url_for("senders.list_senders", account_id=account.id))

    return render_template("senders/form.html", form=form, account=account, sender=sender)


@senders_bp.route("/senders/<int:sender_id>/delete", methods=["POST"])
@login_required
def delete_sender(sender_id):
    sender = db.get_or_404(SenderAddress, sender_id)
    account_id = sender.account_id
    email = sender.email_address
    db.session.delete(sender)
    db.session.commit()
    flash(f"Sender '{email}' deleted.", "success")
    return redirect(url_for("senders.list_senders", account_id=account_id))


@senders_bp.route("/senders/<int:sender_id>/set-status", methods=["POST"])
@login_required
def set_status(sender_id):
    sender = db.get_or_404(SenderAddress, sender_id)
    new_status = request.form.get("status")
    if new_status not in ("active", "cooldown", "warming_up", "disabled"):
        flash("Invalid status.", "error")
        return redirect(url_for("senders.list_senders", account_id=sender.account_id))

    sender.status = new_status
    db.session.commit()
    flash(f"Sender '{sender.email_address}' status set to {new_status}.", "success")
    return redirect(url_for("senders.list_senders", account_id=sender.account_id))


@senders_bp.route("/senders/<int:sender_id>/quota-history")
@login_required
def quota_history(sender_id):
    db.get_or_404(SenderAddress, sender_id)
    # Real quota_checks history lands in Phase 4.
    return jsonify({"history": []})
