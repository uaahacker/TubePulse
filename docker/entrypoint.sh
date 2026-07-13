#!/bin/sh
set -eu

mkdir -p /app/data /app/media /app/staticfiles
python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec "$@"
