#!/bin/sh
set -e
# A copy of the database before a schema change (skipped when there's nothing to migrate), so
# a rollback can restore the exact state from before the release. A failed copy doesn't stop
# the start: the hourly copies are still there.
python -m app.cli backup-before-migration || echo "backup before migration failed" >&2
# Migrate the SQLite file before starting. There is only ever one replica, so no race.
alembic upgrade head
# One worker: SQLite + the in-process cleanup loop expect a single process.
# --proxy-headers: trust X-Forwarded-Proto/For from cloudflared (only reachable in-cluster).
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 \
  --proxy-headers --forwarded-allow-ips='*' --no-server-header "$@"
