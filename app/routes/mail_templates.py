from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.forms import TemplateForm
from app.models.job import Job
from app.models.template import EmailTemplate
from app.services.template_validate import html_size_bytes, validate_html_size, MAX_TEMPLATE_SIZE_BYTES

mail_templates_bp = Blueprint("mail_templates", __name__)


def _resolve_html_body(form) -> str:
    if form.html_file.data and form.html_file.data.filename:
        raw = form.html_file.data.read()
        return raw.decode("utf-8", errors="replace")
    return form.html_paste.data or ""


@mail_templates_bp.route("/")
@login_required
def list_templates():
    templates = EmailTemplate.query.order_by(EmailTemplate.created_at.desc()).all()
    return render_template(
        "mail_templates/list.html", templates=templates, max_size_bytes=MAX_TEMPLATE_SIZE_BYTES
    )


@mail_templates_bp.route("/new", methods=["GET", "POST"])
@login_required
def new_template():
    form = TemplateForm()
    if form.validate_on_submit():
        html_body = _resolve_html_body(form)
        if not html_body.strip():
            flash("Provide an HTML template, either by upload or by pasting it in.", "error")
        else:
            size_error = validate_html_size(html_body)
            if size_error:
                flash(size_error, "error")
            else:
                template = EmailTemplate(
                    name=form.name.data.strip(),
                    description=form.description.data,
                    html_body=html_body,
                    text_body=form.text_body.data or None,
                    subject_default=form.subject_default.data or None,
                    size_bytes=html_size_bytes(html_body),
                )
                db.session.add(template)
                db.session.commit()
                flash(f"Template '{template.name}' created.", "success")
                return redirect(url_for("mail_templates.view_template", template_id=template.id))

    return render_template("mail_templates/form.html", form=form, template=None)


@mail_templates_bp.route("/<int:template_id>")
@login_required
def view_template(template_id):
    template = db.get_or_404(EmailTemplate, template_id)
    return render_template("mail_templates/detail.html", template=template)


@mail_templates_bp.route("/<int:template_id>/edit", methods=["GET", "POST"])
@login_required
def edit_template(template_id):
    template = db.get_or_404(EmailTemplate, template_id)
    form = TemplateForm(obj=template)
    if request.method == "GET":
        form.html_paste.data = template.html_body

    if form.validate_on_submit():
        html_body = _resolve_html_body(form)
        if not html_body.strip():
            flash("Provide an HTML template, either by upload or by pasting it in.", "error")
        else:
            size_error = validate_html_size(html_body)
            if size_error:
                flash(size_error, "error")
            else:
                template.name = form.name.data.strip()
                template.description = form.description.data
                template.html_body = html_body
                template.text_body = form.text_body.data or None
                template.subject_default = form.subject_default.data or None
                template.size_bytes = html_size_bytes(html_body)
                db.session.commit()
                flash(f"Template '{template.name}' updated.", "success")
                return redirect(url_for("mail_templates.view_template", template_id=template.id))

    return render_template("mail_templates/form.html", form=form, template=template)


@mail_templates_bp.route("/<int:template_id>/delete", methods=["POST"])
@login_required
def delete_template(template_id):
    template = db.get_or_404(EmailTemplate, template_id)
    name = template.name

    job_count = Job.query.filter_by(template_id=template.id).count()
    if job_count:
        flash(
            f"Can't delete '{name}': it is used by {job_count} job(s). "
            f"Jobs keep a reference to the exact template they sent.",
            "error",
        )
        return redirect(url_for("mail_templates.view_template", template_id=template.id))

    try:
        db.session.delete(template)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash(f"Can't delete '{name}': it is still referenced by other records.", "error")
        return redirect(url_for("mail_templates.view_template", template_id=template.id))
    flash(f"Template '{name}' deleted.", "success")
    return redirect(url_for("mail_templates.list_templates"))
