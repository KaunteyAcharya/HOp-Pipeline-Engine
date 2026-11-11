FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
RUN pip install .

COPY config ./config
COPY dashboard ./dashboard
COPY docs ./docs

RUN useradd --create-home hostop && mkdir -p data reports exports .cache && chown -R hostop /app
USER hostop

# Default: the n8n hook API. Override the command for the CLI or dashboard (see docker-compose.yml).
EXPOSE 8000 8501
CMD ["uvicorn", "hostop.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
