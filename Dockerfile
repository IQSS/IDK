# syntax=docker/dockerfile:1

FROM python:3.13.3-slim

RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
      build-essential libffi-dev libssl-dev libpng-dev libcairo2-dev pkg-config \
      && rm -rf /var/lib/apt/lists/* \
      && addgroup app \
      && adduser app --ingroup app \
      && mkdir /app \
      && chown app:app /app
USER app
WORKDIR /app
ENV HOME="/app"
ENV PATH="/app/.local/bin:${PATH}"
COPY --chown=app:app pyproject.toml uv.lock* ./
RUN pip install --no-cache-dir uv \
      && uv sync

COPY --chown=app:app . .
EXPOSE 8000
CMD ["uv", "run", "python", "bot.py"]
