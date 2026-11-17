import logging
import os
from logging.handlers import RotatingFileHandler

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def configure_logging(app_or_instance_path, log_filename):
    """
    Accepts either a Flask app (uses app.instance_path) or a raw instance
    path string, so both the web app and the standalone Celery
    entrypoints (which don't run inside a request) can share this setup.
    """
    instance_path = (
        app_or_instance_path.instance_path
        if hasattr(app_or_instance_path, "instance_path")
        else app_or_instance_path
    )
    log_dir = os.path.join(instance_path, "logs")
    os.makedirs(log_dir, exist_ok=True)

    handler = RotatingFileHandler(
        os.path.join(log_dir, log_filename),
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=5,
    )
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    handler.setLevel(logging.INFO)

    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)

    return handler
