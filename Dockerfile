
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1


RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libffi-dev \
        libssl-dev \
        libmagic-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app


COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PATH="/opt/venv/bin:$PATH" \
    APP_HOST=0.0.0.0 \
    APP_PORT=8000

# neonize imports python-magic, which dlopen()s libmagic at runtime via
# ctypes. libmagic-dev lives only in the builder stage; install the runtime
# shared lib here so the app can actually load it.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libmagic1 \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system --gid 1001 app \
    && useradd --system --uid 1001 --gid app --create-home --home-dir /home/app app

WORKDIR /app


COPY --from=builder /opt/venv /opt/venv


COPY app/   ./app/


RUN mkdir -p /home/app/.cache \
    && chown -R app:app /home/app /app

USER app

EXPOSE 8000

CMD ["sh", "-c", "exec uvicorn app.main:app --host ${APP_HOST} --port ${APP_PORT}"]
