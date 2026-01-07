# Use a standard Python 3.13 image
FROM python:3.13-alpine

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Set the working directory to /app
WORKDIR /app

# Copy the requirements file into the container and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code into the container
COPY . .

# Expose port 5807 
EXPOSE 5807

# Run migrations and start Gunicorn production server
CMD sh -c "python manage.py migrate && python manage.py shell -c \"from django.contrib.auth import get_user_model; User = get_user_model(); print('Creating superuser...'); User.objects.create_superuser('admin', 'admin@admin.com', 'admin123'); print('Superuser created!')\" && gunicorn ttscanner_backend.wsgi:application --bind 0.0.0.0:5807"