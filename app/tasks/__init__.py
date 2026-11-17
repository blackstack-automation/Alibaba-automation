from celery import Celery
from celery.schedules import crontab

celery_app = Celery("mail_dashboard")


def init_celery(app):
    celery_app.conf.update(
        broker_url=app.config["REDIS_URL"],
        # No result_backend: job/task progress is tracked in our own
        # jobs/job_allocations/send_logs tables, not via Celery's result
        # store. Configuring one adds a second Redis touchpoint with its
        # own independent (and much more stubborn) retry policy — it was
        # observed to retry reconnecting for 100+ seconds on a failed
        # connection, ignoring the broker-side timeout settings below.
        task_serializer="json",
        accept_content=["json"],
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        # Fail fast instead of hanging the web request when Redis is
        # unreachable (e.g. local dev without Redis running) — see
        # app/routes/jobs.py `_try_dispatch`, which relies on this.
        # task_publish_retry is the one that matters most: Celery retries
        # a failed publish several times by default, each retry paying
        # the full connection-timeout cost again.
        broker_connection_retry_on_startup=False,
        broker_connection_retry=False,
        broker_connection_timeout=2,
        broker_transport_options={
            "socket_connect_timeout": 2,
            "socket_timeout": 2,
            "max_retries": 0,
        },
        task_publish_retry=False,
        beat_schedule={
            "review-sender-health-daily": {
                "task": "tasks.review_sender_health",
                "schedule": crontab(hour=6, minute=0),  # once daily, early morning
            },
            "poll-pending-jobs": {
                "task": "tasks.poll_pending_jobs",
                "schedule": 60.0,  # every minute
            },
        },
    )

    class FlaskTask(celery_app.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery_app.Task = FlaskTask

    # Import task modules so they register with celery_app.
    from app.tasks import dispatch, send, scheduler  # noqa: F401

    return celery_app
