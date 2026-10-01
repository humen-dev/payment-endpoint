# The application image: applies the migrations, then serves the app with gunicorn.
FROM python:3.12-slim AS app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN useradd --create-home app
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=app:app . .
RUN chown app:app /app
USER app

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && exec gunicorn --bind 0.0.0.0:8000 --workers 2 wsgi:app"]


# The same image with the development tools, used to run the tests in Docker.
FROM app AS dev

USER root
RUN pip install --no-cache-dir -r requirements-dev.txt
USER app

CMD ["pytest"]
