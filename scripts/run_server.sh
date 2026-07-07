#!/usr/bin/env bash
set -euo pipefail

cd /root/sign_cloud_v1
source .venv/bin/activate
python scripts/init_db.py
PORT="${PORT:-6666}"
exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT"

