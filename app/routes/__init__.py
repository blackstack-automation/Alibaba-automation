def register_blueprints(app):
    from app.routes.auth import auth_bp
    from app.routes.dashboard import dashboard_bp
    from app.routes.accounts import accounts_bp
    from app.routes.senders import senders_bp
    from app.routes.mail_templates import mail_templates_bp
    from app.routes.recipients import recipients_bp
    from app.routes.jobs import jobs_bp

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(accounts_bp, url_prefix="/accounts")
    app.register_blueprint(senders_bp)
    app.register_blueprint(mail_templates_bp, url_prefix="/mail-templates")
    app.register_blueprint(recipients_bp, url_prefix="/recipients")
    app.register_blueprint(jobs_bp, url_prefix="/jobs")
