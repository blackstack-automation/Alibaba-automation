from app import create_app
from app.tasks import celery_app as celery

flask_app = create_app(log_filename="worker.log")
