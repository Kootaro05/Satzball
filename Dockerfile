FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_DEBUG=0 \
    DJANGO_ALLOWED_HOSTS=* \
    # pip-Hinweise beim Bauen abschalten: root ist im Image gewollt, pip kommt mit dem Basis-Image
    PIP_ROOT_USER_ACTION=ignore \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# Eigener Secret Key nur für den Build, damit keiner im Image landet
RUN DJANGO_SECRET_KEY=build-only python manage.py collectstatic --noinput \
    && useradd --create-home satzball \
    && mkdir -p /app/data \
    && chown satzball /app/data

USER satzball
EXPOSE 8000

# SQLite und Secret Key liegen in /app/data (Volume "satzball-data")
CMD ["sh", "-c", "python manage.py migrate --noinput && gunicorn config.wsgi --bind 0.0.0.0:8000 --workers 2"]
