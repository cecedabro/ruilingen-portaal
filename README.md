# Ruilingen

A small web app where front-of-house colleagues swap shifts, instead of a busy WhatsApp group.
Live at **https://ruilingen.app** (a pilot on a home server: if it's down, use the group chat).

- **Aangeboden / Gezocht:** shifts given away and shifts people look for, with who posted
  first (#1, #2, …), filters by type, day, dagdeel, zaal and availability.
- **Giving away or swapping:** a shift can be given away, swapped ("ruil": you say what you'd
  like back, others propose one of their shifts), or both.
- **Reacting and confirming:** anyone can react; the poster sees reactions in order and picks
  one. When it's confirmed, a ready-made email to planning is one tap away (sent from the
  colleague's own mail app, from an admin-editable template).
- **Joining:** only through an invite link (the main one sits in the group chat
  description). Just a name; no password, no email.
- **Beheer:** invite links (with expiry and use limits), members, zaal/werkplek lists, the
  planning mail template, removing listings.

Dutch UI; code and docs in English. Made-up example data only in this public repository.

## Documentation

| | |
|---|---|
| [docs/architecture.md](docs/architecture.md) | how it works: code map, request flow, login and security, concurrency, migrations |
| [docs/database.md](docs/database.md) | every table and column, status flows, retention |
| [deploy/README.md](deploy/README.md) | how it runs on the homelab cluster and how releases deploy |
| [CONTRIBUTING.md](CONTRIBUTING.md) | local setup, conventions, how changes get merged |
| [CHANGELOG.md](CHANGELOG.md) | releases, with schema/secret/manifest notes |
| [docs/open-questions.md](docs/open-questions.md) | product decisions and their defaults |
| [docs/brief.md](docs/brief.md) | the original project brief |

## Quick start

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
cp .env.example .env                       # DEV_MODE: mails go to the log
.venv/bin/alembic upgrade head             # creates ruilingen.db
.venv/bin/python -m scripts.seed_demo      # optional: made-up colleagues and shifts
.venv/bin/uvicorn app.main:app --reload    # http://localhost:8000
.venv/bin/python -m app.cli join-link      # open this link to join locally
.venv/bin/pytest -q                        # tests
```

## Stack

FastAPI + Jinja2 (server-rendered HTML), SQLAlchemy 2 + Alembic on SQLite, a ~150-line
`app.js` for instant navigation, system fonts. One container, deployed by Flux to a k3s
homelab behind a Cloudflare tunnel. Releases are git tags `vX.Y.Z`.
