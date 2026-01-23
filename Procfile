web: gunicorn ttscanner_backend.wsgi:application --timeout 120 --worker-class gthread --threads 4 --bind 0.0.0.0:$PORT
worker: celery -A ttscanner_backend worker --loglevel=info
beat: celery -A ttscanner_backend beat --loglevel=info