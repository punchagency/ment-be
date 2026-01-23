import os
import ssl
from celery import Celery
from celery.schedules import crontab
from django.conf import settings

# Set the default Django settings module
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ttscanner_backend.settings")

app = Celery("ttscanner_backend")

# Use the configuration from settings.py (which already has your SSL fixes)
app.config_from_object("django.conf:settings", namespace="CELERY")

# Important: Upstash requires specific broker transport options for stability
app.conf.broker_transport_options = {
    'visibility_timeout': 3600,
    'sep': ':',
}

app.autodiscover_tasks()

# Static tasks (The "heartbeat" to check for new files)
app.conf.beat_schedule = {
    'check-and-import-files-every-60-seconds': {
        'task': 'ttscanner.tasks.check_and_import_files',
        'schedule': 60.0,
    },
}

@app.on_after_finalize.connect
def setup_periodic_tasks(sender, **kwargs):
    # We use on_after_finalize to ensure the app is fully loaded
    try:
        from ttscanner.models import FileAssociation
        from ttscanner.tasks import import_file_association
        from celery.schedules import timedelta

        # Query existing files to register their schedules
        files = FileAssociation.objects.all()
        for file in files:
            if file.interval and file.interval.interval_minutes:
                interval_seconds = file.interval.interval_minutes * 60
                sender.add_periodic_task(
                    timedelta(seconds=interval_seconds),
                    import_file_association.s(file.id),
                    name=f"import_{file.file_name}"
                )
    except Exception as e:
        print(f"Error setting up periodic tasks: {e}")