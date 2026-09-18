FROM python:3.12-slim

WORKDIR /app

# Build deps for lxml (trafilatura); removed after install to keep the image lean.
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc libxml2-dev libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY pipeline/ ./pipeline/
COPY services/ ./services/

RUN pip install --no-cache-dir -e . \
    && apt-get purge -y gcc && apt-get autoremove -y

ENV PYTHONUNBUFFERED=1

# Overridden per service in docker-compose.yml
CMD ["python", "-m", "services.enricher.main"]
