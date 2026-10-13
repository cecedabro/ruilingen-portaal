#!/bin/sh
set -e
# Migrate the SQLite file before starting. There is only ever one replica, so no race.
alembic upgrade head
# One worker: SQLite + the in-process cleanup loop expect a single process.
# --proxy-headers: trust X-Forwarded-Proto/For from cloudflared (only reachable in-cluster).
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 \
  --proxy-headers --forwarded-allow-ips='*' --no-server-header "$@"
