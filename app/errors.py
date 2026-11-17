import logging

from flask import render_template, redirect, url_for, flash, request
from flask_wtf.csrf import CSRFError

from app.extensions import db

logger = logging.getLogger(__name__)


def register_error_handlers(app):
    @app.errorhandler(404)
    def not_found(error):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(error):
        logger.exception("Unhandled server error on %s", request.path)
        db.session.rollback()
        return render_template("errors/500.html"), 500

    @app.errorhandler(CSRFError)
    def csrf_error(error):
        flash("Your session expired or the form was stale — please try again.", "error")
        return redirect(request.referrer or url_for("dashboard.index"))
