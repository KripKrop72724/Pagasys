import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("pagasys")

broker = os.environ.get("REDIS_URL") or os.environ.get("RABBIT_URL") or "memory://"
backend = os.environ.get("REDIS_URL") or "cache+memory://"
app.conf.broker_url = broker
app.conf.result_backend = backend

app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
