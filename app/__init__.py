import os

from dotenv import load_dotenv

# Must run before `app.config` is imported: Config reads os.environ at
# class-definition time, so .env has to be loaded first. This matters
# for entrypoints that don't already pre-load .env themselves (the
# `flask` CLI does; a plain `python celery_worker.py` or Celery's own
# CLI does not).
load_dotenv()

from flask import Flask  # noqa: E402

from sqlalchemy import event  # noqa: E402
from sqlalchemy.engine import Engine  # noqa: E402

from app.config import get_config  # noqa: E402
from app.extensions import db, migrate, login_manager, csrf, limiter  # noqa: E402


@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


def create_app(log_filename="app.log"):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(get_config())

    os.makedirs(app.instance_path, exist_ok=True)

    from app.logging_config import configure_logging

    configure_logging(app, log_filename)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    from app.models.user import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    from app.routes import register_blueprints

    register_blueprints(app)

    from app.cli import register_cli

    register_cli(app)

    from app.tasks import init_celery

    init_celery(app)

    from app.errors import register_error_handlers

    register_error_handlers(app)

    return app
