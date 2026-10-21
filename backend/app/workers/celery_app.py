from celery import Celery

from app.core.config import get_settings

celery_app = Celery(
    "researchos",
    broker=get_settings().redis_url,
    include=[
        "app.workers.jobs",
        "app.workers.exports",
        "app.workers.deletions",
        "app.workers.mail",
        "app.workers.maintenance",
    ],
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_transport_options={"visibility_timeout": 300},
    task_default_queue="researchos",
    task_ignore_result=True,
    broker_connection_retry_on_startup=True,
)
