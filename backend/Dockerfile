FROM python:3.12.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt
COPY . ./

# collectstatic imports settings but does not connect to PostgreSQL. These are
# inert build-only values; runtime credentials come from Compose or the host.
RUN SECRET_KEY=build-only-not-a-runtime-secret \
    DEBUG=false ALLOWED_HOSTS=localhost \
    PGDATABASE=unused PGUSER=unused PGPASSWORD=unused PGHOST=localhost \
    python manage.py collectstatic --noinput

EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--access-logfile", "-", "--error-logfile", "-"]
