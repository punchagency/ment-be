from __future__ import absolute_import, unicode_literals
import os
from celery import Celery
from celery.schedules import timedelta

# Set Django settings
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ttscanner_backend.settings")

app = Celery("ttscanner_backend")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.conf.beat_schedule = {
    'import-files-every-30-seconds': { 
        'task': 'ttscanner.tasks.check_and_import_files', 
        'schedule': 30,  
    },
}
app.autodiscover_tasks()


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    from ttscanner.models import FileAssociation
    from ttscanner.tasks import import_file_association

    files = FileAssociation.objects.all()
    for file in files:
        interval_seconds = file.interval.interval_minutes * 60

        # Add a periodic task per file
        sender.add_periodic_task(
            timedelta(seconds=interval_seconds),
            import_file_association.s(file.id),
            name=f"import_{file.file_name}"
        )


