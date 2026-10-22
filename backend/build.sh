#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
python -m pip install -r requirements.txt
python manage.py check
python manage.py collectstatic --noinput
bash scripts/migrate_and_seed.sh
