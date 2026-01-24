web: gunicorn ttscanner_backend.asgi:application -k uvicorn.workers.UvicornWorker --workers 4 --threads 4 --timeout 120 --bind 0.0.0.0:$PORT
worker: celery -A ttscanner_backend worker --loglevel=info --concurrency=1 --maxtasksperchild=3
beat: celery -A ttscanner_backend beat --loglevel=info