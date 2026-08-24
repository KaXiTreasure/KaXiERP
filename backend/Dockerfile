# syntax=docker/dockerfile:1.7
FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app
RUN python -m venv /app/.venv \
    && addgroup --system kaxi \
    && adduser --system --ingroup kaxi --home /app kaxi

COPY pyproject.toml ./
COPY backend ./backend
RUN pip install --no-cache-dir . \
    && python backend/manage.py collectstatic --noinput --settings=config.settings.production \
    && chmod +x /app/backend/entrypoint.sh \
    && chown -R kaxi:kaxi /app

USER kaxi
EXPOSE 8000
ENTRYPOINT ["/app/backend/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--chdir", "/app/backend", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "60", "--access-logfile", "-"]
