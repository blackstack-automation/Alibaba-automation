from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.forms import AccountForm
from app.models.account import Account
from app.models.job_allocation import JobAllocation
from app.models.send_log import SendLog
from app.services.alibaba_client import encrypt_secret, decrypt_secret, test_connection

accounts_bp = Blueprint("accounts", __name__)


@accounts_bp.route("/")
@login_required
def list_accounts():
    accounts = Account.query.order_by(Account.created_at.desc()).all()
    return render_template("accounts/list.html", accounts=accounts)


@accounts_bp.route("/new", methods=["GET", "POST"])
@login_required
def new_account():
    form = AccountForm()
    if form.validate_on_submit():
        if not form.access_key_secret.data:
            form.access_key_secret.errors.append("Access Key Secret is required for a new account.")
        else:
            account = Account(
                label=form.label.data.strip(),
                access_key_id=form.access_key_id.data.strip(),
                access_key_secret_encrypted=encrypt_secret(form.access_key_secret.data),
                region_endpoint=form.region_endpoint.data,
                notes=form.notes.data,
            )
            db.session.add(account)
            db.session.commit()
            flash(f"Account '{account.label}' created.", "success")
            return redirect(url_for("accounts.list_accounts"))

    return render_template("accounts/form.html", form=form, account=None)


@accounts_bp.route("/<int:account_id>/edit", methods=["GET", "POST"])
@login_required
def edit_account(account_id):
    account = db.get_or_404(Account, account_id)
    form = AccountForm(obj=account)
    if request.method == "GET":
        form.access_key_secret.data = ""

    if form.validate_on_submit():
        account.label = form.label.data.strip()
        account.access_key_id = form.access_key_id.data.strip()
        if form.access_key_secret.data:
            account.access_key_secret_encrypted = encrypt_secret(form.access_key_secret.data)
        account.region_endpoint = form.region_endpoint.data
        account.notes = form.notes.data
        db.session.commit()
        flash(f"Account '{account.label}' updated.", "success")
        return redirect(url_for("accounts.list_accounts"))

    return render_template("accounts/form.html", form=form, account=account)


@accounts_bp.route("/<int:account_id>/delete", methods=["POST"])
@login_required
def delete_account(account_id):
    account = db.get_or_404(Account, account_id)
    label = account.label

    sender_ids = [s.id for s in account.senders.all()]
    if sender_ids and (
        JobAllocation.query.filter(JobAllocation.sender_id.in_(sender_ids)).first()
        or SendLog.query.filter(SendLog.sender_id.in_(sender_ids)).first()
    ):
        flash(
            f"Can't delete '{label}': its senders are part of existing jobs / send history, "
            f"which would be orphaned. Set its senders to 'disabled' instead.",
            "error",
        )
        return redirect(url_for("accounts.list_accounts"))

    try:
        db.session.delete(account)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash(f"Can't delete '{label}': it is still referenced by other records.", "error")
        return redirect(url_for("accounts.list_accounts"))
    flash(f"Account '{label}' deleted.", "success")
    return redirect(url_for("accounts.list_accounts"))


@accounts_bp.route("/test-connection", methods=["POST"])
@login_required
def test_connection_new():
    """Test credentials entered on the new-account form (not yet saved)."""
    access_key_id = request.form.get("access_key_id", "").strip()
    access_key_secret = request.form.get("access_key_secret", "").strip()
    region_endpoint = request.form.get("region_endpoint", "dm.aliyuncs.com").strip()

    if not access_key_id or not access_key_secret:
        return jsonify({"ok": False, "error": "Access Key ID and Secret are required."}), 400

    result = test_connection(access_key_id, access_key_secret, region_endpoint)
    return jsonify(result)


@accounts_bp.route("/<int:account_id>/test-connection", methods=["POST"])
@login_required
def test_connection_existing(account_id):
    """Test an existing account's stored credentials, or a replacement secret if provided."""
    account = db.get_or_404(Account, account_id)
    access_key_id = request.form.get("access_key_id", "").strip() or account.access_key_id
    access_key_secret = request.form.get("access_key_secret", "").strip()
    region_endpoint = request.form.get("region_endpoint", "").strip() or account.region_endpoint

    if not access_key_secret:
        access_key_secret = decrypt_secret(account.access_key_secret_encrypted)

    result = test_connection(access_key_id, access_key_secret, region_endpoint)
    return jsonify(result)
