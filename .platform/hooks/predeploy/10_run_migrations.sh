#!/bin/bash
set -e

# Construct DATABASE_URL from RDS variables if available
if [ -n "$RDS_HOSTNAME" ]; then
  export DATABASE_URL="postgres://${RDS_USERNAME}:${RDS_PASSWORD}@${RDS_HOSTNAME}:${RDS_PORT}/${RDS_DB_NAME}"
fi

docker-compose run --rm web python manage.py migrate --noinput