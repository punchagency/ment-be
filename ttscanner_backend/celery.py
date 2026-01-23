import os
import ssl
from celery import Celery
from django.conf import settings

# Set the default Django settings module
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ttscanner_backend.settings")

app = Celery("ttscanner_backend")

raw_url = os.getenv("REDIS_URL", "")
if "${" in raw_url or not raw_url:
    broker_url = "rediss://default:ATkiAAIncDJmOWZhNTA4MDBjMWE0YzhkOWU0ZGE4YzM4Yzg0MDY1NHAyMTQ2MjY@possible-dragon-14626.upstash.io:6379"
else:
    broker_url = raw_url

# Configure Celery
app.conf.update(
    broker_url=broker_url,
    result_backend=broker_url,
    broker_use_ssl={'ssl_cert_reqs': ssl.CERT_NONE},
    redis_backend_use_ssl={'ssl_cert_reqs': ssl.CERT_NONE},
    broker_transport_options={
        'visibility_timeout': 3600,
        'sep': ':',
    },
)

app.autodiscover_tasks()

app.conf.beat_schedule = {
    'check-and-import-files-every-60-seconds': {
        'task': 'ttscanner.tasks.check_and_import_files',
        'schedule': 60.0,
    },
}

@app.on_after_finalize.connect
def setup_periodic_tasks(sender, **kwargs):
    try:
        from ttscanner.models import FileAssociation
        from ttscanner.tasks import import_file_association
        from celery.schedules import timedelta

        files = FileAssociation.objects.all()
        for file in files:
            if file.interval and file.interval.interval_minutes:
                interval_seconds = file.interval.interval_minutes * 60
                sender.add_periodic_task(
                    timedelta(seconds=interval_seconds),
                    import_file_association.s(file.id),
                    name=f"import_{file.file_name}_{file.id}" 
                )
    except Exception as e:
        print(f"Error setting up periodic tasks: {e}")