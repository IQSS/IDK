# syntax=docker/dockerfile:1
FROM python:3.13.3-slim

ARG APP_HOME=/app
ENV HOME=$APP_HOME \
    PATH="$APP_HOME/.local/bin:$PATH" \
    PYTHONUNBUFFERED=1

RUN apt-get update && \
    apt-get -y --no-install-recommends install \
        build-essential libffi-dev libssl-dev libpng-dev libcairo2-dev pkg-config \
 && rm -rf /var/lib/apt/lists/*

RUN mkdir -p $APP_HOME \
 && chgrp -R 0  $APP_HOME \
 && chmod -R g=u $APP_HOME

WORKDIR $APP_HOME

COPY pyproject.toml uv.lock* ./
RUN pip install --no-cache-dir uv \
 && uv sync --frozen --no-cache

COPY . .

EXPOSE 8000
# leave USER unset – OpenShift will inject one
CMD ["uv", "run", "python", "bot.py"]
