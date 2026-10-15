# Architecture

How Ruilingen works, from a tap on the phone to a row in the database. For the tables
themselves see [database.md](database.md); for running it in the cluster see
[../deploy/README.md](../deploy/README.md).

## The short version

One Python process (FastAPI + uvicorn) renders HTML pages on the server (Jinja2 templates)
and stores everything in one SQLite file. There is no separate frontend app, no JavaScript
framework and no API: the browser gets plain HTML, plain forms POST back, and a small
`app.js` makes navigation feel instant.

```
phone ──HTTPS──► Cloudflare ──tunnel──► cloudflared ──HTTP──► uvicorn (1 process)
                                                                 │
                     ┌───────────────────────────────────────────┤ app/main.py
                     │ SessionMiddleware   signed cookie → who you are
                     │ guard               CSRF check, security + cache headers
                     │ GZip
                     ▼
              app/web/routes/*      thin: read the form, call a service, render/redirect
                     │
              app/services/*        all business rules (no HTTP), raise UserError
                     │
              app/models.py         SQLAlchemy tables
                     │
              SQLite file (/data/ruilingen.db on a Longhorn volume)
```

## Code map

```
app/
  main.py            builds the app: middleware, error pages, routers, cleanup loop
  config.py          Settings from environment variables (+ .env locally)
  db.py              SQLite engine (WAL, busy_timeout), Session per request
  models.py          the tables (docs/database.md)
  shifts.py          pure domain helpers: shift types, ShiftInfo, Dutch dates
  mail.py            optional SMTP sending (notifications only)
  cli.py             server-shell commands: admin-link, join-link, set-list
  services/          business rules, one module per area
    board.py           what the boards show: ordering, posting rank, filters, day picker
    listings.py        post / react / confirm / withdraw / remove; Deal (a completed swap)
    invites.py         invite links: the group-chat link, extra links, admin links
    logins.py          one-time login links, email verification
    members.py         names, admin role, deleting members
    appdata.py         runtime settings (zaal/werkplek lists, mail template)
    planning.py        the email to planning, with the admin-editable template
    housekeeping.py    deleting old data
    demo.py            made-up colleagues and shifts for the pilot, removable in one go
    transaction.py     run_write (retry on write conflicts), notification outbox
    errors.py          UserError
  web/
    session.py         current user, require_user/require_admin, CSRF origin check
    responses.py       render(), flash(), redirect(), run_action(), static cache busting
    routes/            public, auth, board, listings, account, admin
  templates/         Jinja2 pages; _macros.html holds the shift card
  static/            style.css, app.js, icon.svg
migrations/          Alembic migrations (run at container start)
tests/               pytest, one file per area
```

**Dependency direction:** routes → services → models. Services never import from `web/`;
`shifts.py` imports nothing from the app. That keeps the rules testable without HTTP and
makes it obvious where a change belongs:

| You want to change… | Look in |
|---|---|
| a rule ("max 30 open listings", "only the owner can confirm") | `services/` |
| what a page shows or which form fields exist | `templates/` + the route in `web/routes/` |
| how it looks | `static/style.css` |
| a stored field | `models.py` + a migration (see below) |

## A request, step by step

Example: Sanne taps **Overnemen** on Daan's shift.

1. The browser POSTs `/listings/42/react` (a normal `<form>`, no JavaScript needed).
2. `SessionMiddleware` decodes the signed `ruilingen_session` cookie.
3. `guard` (main.py) checks `Origin`/`Sec-Fetch-Site`: a POST from another site gets a 403
   (CSRF protection on top of the `SameSite=Lax` cookie).
4. The route `web/routes/listings.py:react` gets its user from `require_user`, which loads
   the user and checks the cookie's `session_epoch` (so "log out everywhere" works).
5. It calls `run_action(…, listings.react, …)`, which runs the service inside
   `transaction.run_write`: a fresh transaction, committed at the end, retried if SQLite
   reports a write conflict.
6. `services/listings.py:react` validates (listing still open, not your own, not already
   reacted), inserts the reaction, and calls `notify(…, mail=True)` for Daan: an in-app
   notification row, plus an email queued on the session if Daan verified an address and mail
   is on. (Reactions are the only event that mails; everything else is bell-only.)
7. After the commit, queued mails go to a background task; the user gets a flash message
   ("Gereageerd.") and a `303` redirect back to the board (POST → redirect → GET, so a
   refresh never resubmits).
8. The GET renders `board.html`; `render()` adds the tab-bar counts and the bell.

A broken rule anywhere in a service raises `UserError("…")` with a Dutch message; the route
turns it into an error flash and the same redirect.

## Frontend

- **Server-rendered.** Every page is complete HTML. Templates extend `base.html` (header, tab
  bar, flash messages, footer); `_macros.html` has the shift card used on every board: a
  `<details>` element whose two-line summary (day + time + type, then who + status) is the
  list view, and which opens on tap to show zaal/werkplek/opmerking and the actions.
- **No framework.** `static/app.js` (~150 lines) only does progressive enhancement:
  - *instant navigation*: the four tabs are fetched in the background after a page loads
    (with an `X-Prefetch` header) and links swap `<body>` in place instead of reloading. A
    background fetch never uses up flash messages (`render()` checks the header), and
    `/meldingen` is never prefetched because opening it marks notifications read;
  - filters apply on change; Weggeven/Zoeken switches without a request;
  - copy buttons, "are you sure?" dialogs, the light/dark switch (cookie `theme`).
  Without JavaScript everything still works with full page loads.
- **Styling.** One stylesheet with design tokens (CSS variables) at the top; dark mode
  redefines the tokens under `[data-theme="dark"]`, which the server sets from the cookie
  (so no flash of the wrong theme). System fonts only.
- **Caching.** Asset URLs carry `?v=<hash of all static files>`, so they're cached for a year
  and a deploy still reaches everyone at once. HTML is `no-store`.

## Login and security

There are no passwords and no email login. Ways in:

| How | Where | Notes |
|---|---|---|
| Invite link `/join/<code>` | group chat description, or extra links from Beheer | ask a unique name, then log in |
| One-time login link `/login/<token>` | Account → "Ander apparaat koppelen", or Beheer → Inloglink | single use, 20 min (admin: 24 h), stored hashed |
| `python -m app.cli admin-link "Name"` | server shell | bootstrap the first admin |

- **Session:** signed cookie (`SESSION_SECRET`), rolling 365 days, `HttpOnly`, `Secure`,
  `SameSite=Lax`. It contains the user id and `session_epoch`; bumping the epoch logs out
  every device.
- **Link previews:** opening a one-time link only shows a button; the POST consumes it. Chat
  apps that "open" links for a preview can't burn them.
- **Admin links** are always single use and valid 24 hours, whatever the form says.
- **Headers:** strict CSP (`'self'` only, no inline scripts or styles), `nosniff`,
  `frame-ancestors 'none'`, `Referrer-Policy: same-origin`.
- **Open redirects:** `?next=` only accepts local paths (`safe_next`).
- **Behind the tunnel:** uvicorn runs with `--proxy-headers`, so `request.client.host` is the
  real client IP from `X-Forwarded-For`.
- **Privacy:** only a name is required; email is optional and only for notifications. Old
  listings, notifications and tokens are deleted after `RETENTION_DAYS` (housekeeping loop in
  main.py). Members (or admins) can delete an account with everything in it.

## Who was first, and concurrency

Colleagues care about order, so it's made unambiguous and enforced by the database:

- **Posting rank (#1, #2, …)** on the boards is the order of `listings.created_at`,
  computed over the whole board before filtering (`board.posting_ranks`).
- **Reactions** are ordered by `(created_at, id)`; the owner sees them as #1, #2, … but may
  pick any of them.
- **One reaction per person per listing** is a partial unique index (`uq_reaction_pending`),
  so a double tap can't create two.
- **A shift can only be given away once.** `listings.accept` flips the listing with
  `UPDATE … WHERE status = 'open'` and the reaction with `… WHERE status = 'pending'`; if
  either affects zero rows, someone else was faster and the user gets a clear message.
- **Invite links with a use limit** are counted the same way (`UPDATE … WHERE uses < max`).
- **SQLite transactions:** WAL mode serialises writers; a transaction that read stale data
  fails rather than overwriting, and `run_write` retries it on fresh data. There's a test that
  races two threads confirming two different reactions on the same shift.

This is why the app runs as **exactly one process** (one replica, one uvicorn worker): SQLite
on a single volume, and the housekeeping loop running inside it.

## Swaps (ruilen)

An offer has a `mode`: **give** (anyone can take it), **trade** (a reaction must carry a shift
back) or **both**. A swap offer can say what the poster would like back (a date range and/or
types); that's a hint only, a proposal outside it is allowed and the owner sees a small
"buiten je wens" note. The reactor types the returned shift in (including its date) or picks one
of their own open offers (`offer_listing_id`); in that case that offer is taken down when the
owner confirms. Confirming works exactly as for a plain reaction (one conditional UPDATE,
so it can't happen twice), and `listings.Deal.return_shift` carries the second shift to "Mijn"
and to the planning mail. A swap proposal is still a reaction: it's ordered by time, shows up
in "Mijn" for the owner and is the one event that sends an email.

## The email to planning

When a swap (or give-away) is confirmed, "Mijn" shows a ready-made email (`services/planning.py`): **To**
planning (`PLANNING_EMAIL`), **Cc** both colleagues if they have an address, subject and body
from a template. Admins edit the templates on Beheer (one for a shift given away, one for a real swap with
two shifts) with placeholders such as `{gever}`, `{nemer}`, `{datum}`, `{details}` and, for a
swap, `{datum_terug}`, `{details_terug}`. The app doesn't send it: **Mail naar planning** opens the
colleague's own mail app with everything filled in (a `mailto:` link), so planning keeps
getting it from a colleague. **Verstuurd** records that it was sent and tells the other one.

## Data changes and migrations

The schema is managed with Alembic (`migrations/`). The container runs
`alembic upgrade head` before starting, and migrations only go forward.

1. Change `app/models.py`.
2. `.venv/bin/alembic revision --autogenerate -m "what changed"` and **read the result**:
   replace `app.models.UTCDateTime()` by `sa.DateTime()` (migrations must not import the app)
   and add any data migration by hand.
3. Extend `tests/test_migrations.py` if existing rows are transformed.
4. Note it as a schema change in `CHANGELOG.md` (a rollback then needs a database restore).

SQLite can't alter most columns, so Alembic's batch mode rebuilds tables (copy → drop →
rename). `migrations/env.py` turns foreign keys off for that, or dropping `users` would
cascade-delete everything. `tests/test_migrations.py` checks that data survives.

## Testing

```bash
.venv/bin/pytest -q          # ~60 tests, a few seconds
```

Tests run against a temporary SQLite file with the real app (`TestClient`), logging in as
made-up colleagues (`tests/conftest.py`). One file per area: `test_auth`, `test_listings`,
`test_board`, `test_account`, `test_admin`, `test_planning`, `test_pages`, `test_migrations`.
CI runs lint (ruff), the tests, and `alembic check` (models and migrations agree) on every
push and pull request.
