# GLTG -- Giraffe Lead-Time Graph standalone API service
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    GLTG_HOST=0.0.0.0 \
    GLTG_PORT=8090

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir -e ".[api]"

EXPOSE 8090

# Honors GLTG_HOST / GLTG_PORT at runtime.
CMD ["sh", "-c", "uvicorn gltg.api.main:app --host ${GLTG_HOST:-0.0.0.0} --port ${GLTG_PORT:-8090}"]
