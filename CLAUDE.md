# Ruilingen Portaal

Shift-swap board for front-of-house colleagues. FastAPI + Jinja2, SQLite, Dutch UI, code in English.
How it works: docs/architecture.md (code map, request flow, security, concurrency) and
docs/database.md (tables). Deployment: deploy/README.md. Release notes: CHANGELOG.md.
Conventions and merge rules: CONTRIBUTING.md.

## Where things go
- Rules → `app/services/<area>.py` (no HTTP; raise `UserError` with a Dutch message).
- Pages → `app/templates/` + a thin route in `app/web/routes/<area>.py` (POST → redirect).
- Writes that can race go through `services.transaction.run_write`.
- Admin-editable text/lists → `app_settings` via `services/appdata.py`, never hardcoded
  (employer-identifying values must stay out of this public repo).
- Tests → `tests/test_<area>.py`, helpers in `tests/helpers.py`.

## Commands
```bash
.venv/bin/pytest -q
.venv/bin/ruff check . && .venv/bin/ruff format .
.venv/bin/alembic revision --autogenerate -m "..."   # after changing app/models.py; read the result
.venv/bin/uvicorn app.main:app --reload             # .env from .env.example; join link: python -m app.cli join-link
```

## Deployment (live at https://ruilingen.app)
- **Release-only:** a `vX.Y.Z` tag → image `X.Y.Z` → Flux image automation in cecedabro/homelab
  deploys it. Pushes to `main` build images but don't deploy. Keep the `{{version}}` tag in CI.
- Live manifests live in cecedabro/homelab (`apps/ruilingen/`); `deploy/homelab/` is a reference
  copy. The image line there carries `# {"$imagepolicy": "flux-system:ruilingen"}`; keep it.
- Every release gets a CHANGELOG entry stating **schema change / new secret keys / manifest
  changes**, even when "none".
  - A schema change means a rollback needs a DB restore: say so.
  - A new required secret key must be added to OpenBao `ruilingen/app` before the release
    (only `SESSION_SECRET` and `PLANNING_EMAIL` exist): tell the owner, or the pod won't start.
  - A manifest change needs updating `deploy/homelab/` and telling the owner to change homelab.

## Must stay true
- Exactly 1 replica + Recreate (SQLite on a RWO volume); one uvicorn worker (the cleanup
  loop runs in-process).
- Port 8000. `GET /healthz` returns 200 without auth (probes + status dot).
- Runs as UID 10001 with a read-only root filesystem: only `/data` and `/tmp` are writable.
  Never write files elsewhere at runtime.
- Behind a Cloudflare tunnel: keep `--proxy-headers --forwarded-allow-ips='*'` in
  docker-entrypoint.sh. `request.client.host` is the real client IP (from X-Forwarded-For);
  use it for any per-IP rate limiting.
- `BASE_URL=https://ruilingen.app`, `MAIL_BACKEND=none` in production for now: features that
  need mail must degrade gracefully when `settings.mail_enabled` is false.
- Migrations run at container start and only go forward. SQLite batch migrations rebuild tables:
  tests/test_migrations.py checks data survives; extend it for new migrations.
- The repo is public: no real names, email addresses, schedules or employer branding. Made-up
  example data only (`@voorbeeld.nl`).

## UI
Lean: server-rendered HTML, plain form POST → redirect, no JS framework, system fonts, no
explanations of shift codes (everyone knows them). `app.js` is progressive enhancement only
(tab prefetch + in-place swaps, filters, copy, confirms, theme); every page works without it.
Design tokens are CSS variables at the top of style.css; dark mode redefines them.
