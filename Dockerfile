# Both stages use Debian bookworm so the Node binary has compatible libraries.
FROM node:22-bookworm-slim AS node_runtime
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src \
    PORT=8080

RUN apt-get update \
    && apt-get install -y --no-install-recommends libstdc++6 ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=node_runtime /usr/local/bin/node /usr/local/bin/node

WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

# Explicit copies prevent datasets, exports, credentials and local caches
# from accidentally becoming part of the public service's container image.
COPY app.py ./
COPY src/ ./src/
COPY vendor/trackspace/ ./vendor/trackspace/
COPY .streamlit/config.toml ./.streamlit/config.toml
COPY deploy/start.sh ./deploy/start.sh

RUN useradd --create-home --uid 10001 appuser \
    && python -c "from trackaccess.trackspace_bridge import availability; ok, reason = availability(); assert ok, reason; print(reason)"
USER appuser

EXPOSE 8080
CMD ["sh", "/app/deploy/start.sh"]
