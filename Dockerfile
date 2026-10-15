FROM python:3.12.15-slim@sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.lock .
RUN python -m pip install --no-cache-dir --require-hashes -r requirements.lock
COPY . .
RUN DJANGO_SECRET_KEY=build-only-placeholder-never-used-to-serve-real-requests-123456789 \
    DATABASE_URL=postgresql://build@127.0.0.1/unused \
    DJANGO_SETTINGS_MODULE=config.settings.production ALLOWED_HOSTS=localhost \
    python manage.py collectstatic --noinput
USER 10001
CMD ["sh", "-c", "python manage.py migrate --noinput && exec gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 2 --access-logfile - --error-logfile -"]

