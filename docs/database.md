# Database

One SQLite file: `/data/ruilingen.db` in the cluster (Longhorn volume, backed up nightly),
`./ruilingen.db` locally. Tables are defined in [`app/models.py`](../app/models.py) and
changed only through Alembic migrations (see [architecture.md](architecture.md#data-changes-and-migrations)).

Conventions:
- Timestamps are stored as UTC (`UTCDateTime`) and shown in Europe/Amsterdam.
- Shift times are `"HH:MM"` strings; an end before the start means past midnight.
- Statuses are short strings. The allowed values are the `StrEnum`s in `models.py`.
- Deleting a user cascades (`ON DELETE CASCADE`) to everything they own.

## Tables

```
users ─┬─< listings ─┬─< reactions >── users
       │             └── mail_sent_by ──> users
       ├─< reactions
       ├─< notifications
       ├─< login_tokens
       └─< invite_links (created_by)
app_settings  (key/value, no relations)
```

### `users`: a colleague

| Column | Notes |
|---|---|
| `id` | |
| `name` | shown to everyone; unique (case-insensitive, checked in `services/members.py`) |
| `email` | optional, only for notification mails; set after verification; unique |
| `email_notifications` | mails on/off (only matters with an email) |
| `is_admin` | can use Beheer |
| `is_active` | inactive users can't log in |
| `session_epoch` | bumped by "log out everywhere"; cookies with an older value stop working |
| `created_at`, `last_login_at` | |

### `listings`: a shift on a board

| Column | Notes |
|---|---|
| `kind` | `offer` (Aangeboden: given away) or `wanted` (Gezocht: looked for) |
| `user_id` | who posted it |
| `date` | the shift date |
| `shift_type` | offer: one type, e.g. `HG` or `Inwerk` |
| `wanted_types` | wanted: acceptable types, comma separated (`H,HG,G`) |
| `start`, `end` | offer: required `HH:MM` |
| `daypart` | wanted: optional `ochtend` / `middag` / `avond` |
| `hall`, `workplace` | offer: optional, chosen from the admin lists |
| `note` | "opmerking", max 200 characters |
| `status` | `open` → `taken` (owner confirmed a reaction) or `removed` |
| `created_at` | posting time: decides the #1, #2 posting rank |
| `closed_at` | when it became taken/removed |
| `mail_sent_at`, `mail_sent_by_id` | someone said "Verstuurd" for the planning mail |

### `reactions`: someone responding to a listing

| Column | Notes |
|---|---|
| `listing_id`, `user_id` | |
| `status` | `pending` → `accepted` / `declined` / `withdrawn` / `expired` |
| `offer_type`, `offer_start`, `offer_end`, `offer_hall`, `offer_workplace` | only on a wanted listing: the shift being offered in reply |
| `offer_daypart` | legacy (0.3–0.4), no longer written |
| `created_at` | decides "who was first" (with `id` as tie-breaker) |
| `decided_at` | when the status left `pending` |

Index `uq_reaction_pending`: unique `(listing_id, user_id)` **where** `status = 'pending'`:
one open reaction per person per listing, enforced by SQLite itself.

```
listing:   open ──(owner confirms a reaction)──► taken
             └───(owner or admin removes it)───► removed

reaction:  pending ──► accepted    owner chose this one (the listing becomes taken)
                   ├─► declined    owner said no
                   ├─► withdrawn   reactor took it back
                   └─► expired     another one was chosen, or the listing was removed
```

A **completed swap** is a `taken` listing plus its `accepted` reaction. Who gives and who
takes depends on the kind (`services/listings.py:Deal`): on an offer the poster gives the
shift away; on a wanted listing the reactor gives theirs.

### `notifications`: the bell

`user_id`, `text`, `link` (where tapping it goes), `created_at`, `read_at` (set when
`/meldingen` is opened).

### `login_tokens`: one-time links

`user_id`, `token_hash` (SHA-256 of the token; the token itself is never stored),
`expires_at`, `used_at`, and `email`: when set, the token verifies that address instead of
logging in.

### `invite_links`: ways to join

| Column | Notes |
|---|---|
| `code` | the random part of `/join/<code>` |
| `label` | a name for admins ("Groepsapp", "nieuwe lichting") |
| `role` | `member` or `admin` (admin links: always 1 use, 24 hours) |
| `is_main` | the group-chat link (exactly one non-revoked) |
| `max_uses`, `uses` | limit (empty = unlimited) and how many joined through it |
| `expires_at`, `revoked_at` | empty = never expires / still active |
| `created_by_id`, `created_at` | |

### `app_settings`: runtime settings

Key/value rows that admins change on Beheer, so employer-specific text stays out of this
public repository:

| Key | Value |
|---|---|
| `halls` | zaal choices, one per line |
| `workplaces` | werkplek choices, one per line |
| `mail_subject`, `mail_body` | the planning mail template (absent = the default in `services/planning.py`) |
| `demo_user_ids` | ids of the made-up demo colleagues (`services/demo.py`), so they can be removed in one go |

## Retention

`services/housekeeping.py` runs every 6 hours and deletes:
- listings whose date is more than `RETENTION_DAYS` (default 42) ago, with their reactions;
- removed listings closed more than `RETENTION_DAYS` ago;
- notifications older than `RETENTION_DAYS`;
- login tokens that expired more than a day ago.

## Looking at the live data

The image has no `sqlite3` CLI. A read-only peek:

```bash
kubectl -n ruilingen exec deploy/ruilingen -- python -c \
  "import sqlite3; d=sqlite3.connect('/data/ruilingen.db'); print(d.execute('select count(*) from users').fetchone())"
```

For real changes, scale the deployment to 0, copy the file off the volume, and work on the copy.
