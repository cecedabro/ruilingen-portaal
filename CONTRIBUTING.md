# Contributing

Thanks for helping. Ruilingen is a small app for real colleagues, so changes go through the
owner: **only @cecedabro merges to `main` and makes releases.**

## How changes get in

1. Fork the repo (or create a branch if you have access) and make your change there.
2. Open a pull request against `main`. CI runs lint, tests and a migration check.
3. The owner reviews it (`.github/CODEOWNERS`). A PR can only be merged with their approval
   and green CI; `main` can't be force-pushed or deleted.
4. Merging to `main` does **not** deploy anything. Only a release tag `vX.Y.Z`, pushed by the
   owner, builds the image that the cluster deploys (see [deploy/README.md](deploy/README.md)).

CI workflows from first-time contributors need the owner's approval before they run.

## Local setup

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
cp .env.example .env
.venv/bin/alembic upgrade head
.venv/bin/python -m scripts.seed_demo        # optional: made-up colleagues
.venv/bin/uvicorn app.main:app --reload      # http://localhost:8000
.venv/bin/python -m app.cli join-link        # the local join link
```

## Before you open a PR

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pytest -q
```

- Read [docs/architecture.md](docs/architecture.md) first: it says where each kind of change
  belongs (rules in `app/services/`, pages in `app/templates/` + `app/web/routes/`).
- Business rules raise `UserError` with a Dutch message; routes stay thin.
- New behaviour gets a test in the matching `tests/test_<area>.py`.
- Schema changes need a migration (see the architecture doc) and a `CHANGELOG.md` note.
- UI text is Dutch; code, comments and docs are English.
- Keep it lean: no JavaScript framework, no external fonts/CDNs, server-rendered HTML.

## Privacy rules for this repository

This repository is public. Never commit real names, email addresses, rosters, room names or
anything identifying the employer. Use made-up example data (`@voorbeeld.nl`, "Grote Zaal").
Real values live in the database (admin settings) or in the cluster's secrets.
