# syntax=docker/dockerfile:1

ARG PYTHON_VERSION
FROM python:3.13.3-slim

# rest of your Dockerfile…
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential libffi-dev libssl-dev libpng-dev libcairo2-dev pkg-config \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml uv.lock* ./
RUN pip install --no-cache-dir uv \
 && uv sync

COPY . .
EXPOSE 8000
CMD ["uv", "run", "python", "bot.py"]
