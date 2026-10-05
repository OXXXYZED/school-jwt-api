FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN DJANGO_SECRET_KEY=collectstatic-only python manage.py collectstatic --noinput \
    && useradd --system --uid 10001 --no-create-home app \
    && mkdir /data && chown app:app /data

USER app
ENV DJANGO_SQLITE_PATH=/data/db.sqlite3
EXPOSE 8000

# A single process keeps the in-memory throttle counters (login rate limit) consistent;
# threads handle concurrency. Scale with more workers only together with a shared cache.
CMD ["sh", "-c", "python manage.py migrate --noinput && exec gunicorn config.wsgi --bind 0.0.0.0:8000 --workers 1 --threads 4 --no-control-socket --access-logfile -"]
