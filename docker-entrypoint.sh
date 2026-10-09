#!/bin/sh
set -e

# Start as root only long enough to hand the upload/static volumes to the
# unprivileged `app` user (volumes created by older root-run images are owned
# by root), then drop privileges for migrate/collectstatic/gunicorn.
if [ "$(id -u)" = "0" ]; then
    chown -R app:app /app/media /app/staticfiles
    exec setpriv --reuid=app --regid=app --init-groups "$@"
fi

exec "$@"
