from celery import Celery
from app.core.config import settings

# Initialize Celery app
celery_app = Celery(
    "bill_payment",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.tasks.recurring_payments",
        "app.tasks.reconciliation"
    ]
)

# Configure Celery
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 hour
    task_soft_time_limit=1800,  # 30 minutes
    worker_max_tasks_per_child=200,
    broker_connection_retry_on_startup=True,
    broker_connection_max_retries=10,
    result_expires=86400,  # 1 day
)

# Configure Celery Beat schedule
celery_app.conf.beat_schedule = {
    "process-recurring-payments": {
        "task": "app.tasks.recurring_payments.process_recurring_payments",
        "schedule": 3600.0,  # Every hour
    },
    "reconcile-transactions": {
        "task": "app.tasks.reconciliation.reconcile_transactions",
        "schedule": 3600.0 * 6,  # Every 6 hours
    },
    "cleanup-expired-idempotency-keys": {
        "task": "app.tasks.reconciliation.cleanup_expired_idempotency_keys",
        "schedule": 3600.0 * 24,  # Every 24 hours
    },
}