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

# Expose port 8000 for the Django application
EXPOSE 8000

# Run migrations and start the Django development server
CMD sh -c "python manage.py migrate && python manage.py runserver 0.0.0.0:8000"