FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ .

# Run as an unprivileged user so a bug in Django or a dependency doesn't hand
# an attacker root inside the container. The entrypoint fixes volume
# ownership and then switches to this user.
RUN useradd --system --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /app/media /app/staticfiles \
    && chown app:app /app/media /app/staticfiles
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh
ENTRYPOINT ["docker-entrypoint.sh"]

EXPOSE 8000
