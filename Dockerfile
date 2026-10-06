FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY retail ./retail
COPY data ./data

RUN pip install --no-cache-dir -e .

ENV PYTHONUNBUFFERED=1 \
    MONGODB_URI=mongodb://precios-mongo:27017 \
    MONGODB_DB=scraping \
    QDRANT_URL=http://precios-qdrant:6333 \
    REDIS_URL=redis://precios-redis:6379/0

EXPOSE 8080

CMD ["uvicorn", "retail.web.app:app", "--host", "0.0.0.0", "--port", "8080"]
