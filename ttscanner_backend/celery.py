# ttscanner_backend/celery.py
from __future__ import absolute_import, unicode_literals
import os
import ssl
from celery import Celery
from celery.schedules import timedelta
from dotenv import load_dotenv

load_dotenv()
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ttscanner_backend.settings")

redis_url = os.getenv("REDIS_URL")

# FIX: Handle the ${REDIS_URL} placeholder issue
if not redis_url or '${REDIS_URL}' in redis_url:
    # If REDIS_URL is not set or contains placeholder, use direct URL
    redis_url = "rediss://default:ATkiAAIncDJmOWZhNTA4MDBjMWE0YzhkOWU0ZGE4YzM4Yzg0MDY1NHAyMTQ2MjY@possible-dragon-14626.upstash.io:6379"

app = Celery("ttscanner_backend")

# Configure Celery BEFORE loading Django settings
app.conf.update(
    broker_url=redis_url,
    result_backend=redis_url,
    broker_use_ssl={'ssl_cert_reqs': ssl.CERT_NONE},
    redis_backend_use_ssl={'ssl_cert_reqs': ssl.CERT_NONE},
    broker_connection_retry_on_startup=True,
)

# Now load Django settings
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.beat_schedule = {
    'check-and-import-files-every-60-seconds': {
        'task': 'ttscanner.tasks.check_and_import_files',
        'schedule': 60,
    },
}

@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    from ttscanner.models import FileAssociation
    from ttscanner.tasks import import_file_association

    files = FileAssociation.objects.all()
    for file in files:
        if not file.interval or not file.interval.interval_minutes:
            print(f"[SKIP] {file.file_name}: no interval set")
            continue

        interval_seconds = file.interval.interval_minutes * 60

        sender.add_periodic_task(
            timedelta(seconds=interval_seconds),
            import_file_association.s(file.id),
            name=f"import_{file.file_name}"
        )