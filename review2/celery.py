import os

from celery import Celery

from review2 import REDIS_HOST, REDIS_PORT

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "review2.settings")

celery_app = Celery("ml_model", broker=f"redis://{REDIS_HOST}:{REDIS_PORT}/0")
celery_app.config_from_object("django.conf:settings", namespace="CELERY")
celery_app.autodiscover_tasks()
