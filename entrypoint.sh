#!/bin/sh
set -e

python manage.py migrate --noinput
python manage.py seed_fleet --if-empty

exec gunicorn config.wsgi:application \
  --bind "0.0.0.0:${PORT:-8080}" \
  --workers 2 \
  --threads 4 \
  --timeout 120
