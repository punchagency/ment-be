web: gunicorn ttscanner_backend.wsgi:application --timeout 120 --workers 2 --threads 1 --bind 0.0.0.0:$PORT
worker: celery -A ttscanner_backend worker --loglevel=info --concurrency=1 --maxtasksperchild=3
beat: celery -A ttscanner_backend beat --loglevel=info