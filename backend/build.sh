#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
for variable in SECRET_KEY ALLOWED_HOSTS PGDATABASE PGUSER PGPASSWORD PGHOST; do
  if [[ -z "${!variable:-}" ]]; then
    printf 'Missing required deployment variable: %s\n' "$variable" >&2
    exit 1
  fi
done
python -m pip install -r requirements.txt
python manage.py check
python manage.py collectstatic --noinput
bash scripts/migrate_and_seed.sh
