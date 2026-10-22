#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
export DJANGO_SETTINGS_MODULE=config.settings
for variable in SECRET_KEY ALLOWED_HOSTS PGDATABASE PGUSER PGPASSWORD PGHOST; do
  if [[ -z "${!variable:-}" ]]; then
    printf 'Missing required deployment variable: %s\n' "$variable" >&2
    exit 1
  fi
done

# Confirm the configured database before any schema or seed writes. Never print
# credentials or a connection string in deployment logs.
python - <<'PY'
import os

import django
from django.db import connection

django.setup()
with connection.cursor() as cursor:
    cursor.execute("SELECT current_database()")
    actual_database = cursor.fetchone()[0]
if actual_database != os.environ["PGDATABASE"]:
    raise SystemExit("Configured PostgreSQL database does not match the connection target.")
print("PostgreSQL deployment target verified.")
PY

python manage.py migrate --noinput
python manage.py seed_data
