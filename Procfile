web: gunicorn ttscanner_backend.wsgi:application --bind 0.0.0.0:$PORT
worker: celery -A ttscanner_backend worker --loglevel=info
beat: celery -A ttscanner_backend beat --loglevel=info