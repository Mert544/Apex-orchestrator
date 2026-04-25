# syntax=docker/dockerfile:1
FROM python:3.11-slim AS base

WORKDIR /app

# Install git for repo operations
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY README.md .
COPY config/ config/

# Install dependencies
RUN pip install --no-cache-dir -e ".[dev]"

COPY app/ app/
COPY scripts/ scripts/
COPY examples/ examples/

# Create .apex directory for reports and memory
RUN mkdir -p .apex

ENV PYTHONPATH=/app
ENV EPISTEMIC_TARGET_ROOT=/app

EXPOSE 8767

CMD ["python", "-m", "app.main"]
