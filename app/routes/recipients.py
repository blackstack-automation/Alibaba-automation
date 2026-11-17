from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user

from app.extensions import db
from app.models.recipient import RecipientList, Recipient
from app.services import csv_import

recipients_bp = Blueprint("recipients", __name__)


def _mapping_from_form():
    return {
        key[len("map__"):]: value
        for key, value in request.form.items()
        if key.startswith("map__")
    }


@recipients_bp.route("/")
@login_required
def list_recipients():
    lists = RecipientList.query.order_by(RecipientList.created_at.desc()).all()
    return render_template("recipients/list.html", lists=lists)


@recipients_bp.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    if request.method == "GET":
        return render_template("recipients/upload.html", stage="upload")

    # Stage 3: confirm — commit to DB.
    if request.form.get("confirm"):
        mapping = _mapping_from_form()
        upload_token = request.form["upload_token"]
        try:
            recipient_list = csv_import.commit_import(
                upload_token=upload_token,
                mapping=mapping,
                list_name=request.form.get("list_name", "Untitled list"),
                source_filename=request.form.get("source_filename", ""),
                uploaded_by_id=current_user.id,
            )
        except FileNotFoundError:
            flash("Upload expired. Please upload the file again.", "error")
            return redirect(url_for("recipients.upload"))

        flash(f"Recipient list '{recipient_list.name}' imported.", "success")
        return redirect(url_for("recipients.view_list", list_id=recipient_list.id))

    # Stage 2: mapping submitted — show validation preview.
    if request.form.get("upload_token"):
        mapping = _mapping_from_form()
        upload_token = request.form["upload_token"]
        if "email_address" not in mapping.values():
            flash("Map at least one column to Email address.", "error")
            columns_info = csv_import.read_columns(upload_token)
            return render_template(
                "recipients/upload.html",
                stage="map",
                upload_token=upload_token,
                source_filename=request.form.get("source_filename", ""),
                list_name=request.form.get("list_name", ""),
                guessed_mapping=mapping,
                **columns_info,
            )

        try:
            summary = csv_import.preview_import(upload_token, mapping)
        except FileNotFoundError:
            flash("Upload expired. Please upload the file again.", "error")
            return redirect(url_for("recipients.upload"))

        return render_template(
            "recipients/upload.html",
            stage="review",
            upload_token=upload_token,
            mapping=mapping,
            list_name=request.form.get("list_name", ""),
            source_filename=request.form.get("source_filename", ""),
            **summary,
        )

    # Stage 1: file submitted — detect columns.
    file = request.files.get("file")
    if not file or not file.filename:
        flash("Choose a CSV or XLSX file to upload.", "error")
        return render_template("recipients/upload.html", stage="upload")

    try:
        upload_token = csv_import.save_upload(file)
        columns_info = csv_import.read_columns(upload_token)
    except ValueError as exc:
        flash(str(exc), "error")
        return render_template("recipients/upload.html", stage="upload")

    default_name = file.filename.rsplit(".", 1)[0]
    return render_template(
        "recipients/upload.html",
        stage="map",
        upload_token=upload_token,
        source_filename=file.filename,
        list_name=default_name,
        guessed_mapping=csv_import.guess_mapping(columns_info["columns"]),
        **columns_info,
    )


@recipients_bp.route("/<int:list_id>")
@login_required
def view_list(list_id):
    recipient_list = db.get_or_404(RecipientList, list_id)
    page = request.args.get("page", 1, type=int)
    search = request.args.get("q", "").strip()

    query = Recipient.query.filter_by(list_id=list_id)
    if search:
        query = query.filter(Recipient.email_address.ilike(f"%{search}%"))

    pagination = query.order_by(Recipient.id).paginate(page=page, per_page=50, error_out=False)
    return render_template(
        "recipients/detail.html", recipient_list=recipient_list, pagination=pagination, search=search
    )


@recipients_bp.route("/<int:list_id>/delete", methods=["POST"])
@login_required
def delete_list(list_id):
    recipient_list = db.get_or_404(RecipientList, list_id)
    name = recipient_list.name
    db.session.delete(recipient_list)
    db.session.commit()
    flash(f"Recipient list '{name}' deleted.", "success")
    return redirect(url_for("recipients.list_recipients"))
