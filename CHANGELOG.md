# Changelog

Releases are deployed automatically when the `vX.Y.Z` tag is pushed (see
[deploy/README.md](deploy/README.md)). Every release lists these three, even when the answer is
"none", because they decide whether a deploy or rollback needs manual work:

- **Schema change**: migrations run at start and only go forward. If yes, a rollback also needs
  a database restore (Longhorn backup from before the release).
- **New secret keys**: must be in OpenBao `ruilingen/app` *before* the release, or the pod won't start.
- **Manifest changes**: must be made in the homelab repo (`apps/ruilingen/`) as well.

## Unreleased
- Schema change: none
- New secret keys: none
- Manifest changes: none

## 0.2.0 (2026-10-13)
- Join via a group link with just a name (`/join/<code>`); email optional and verified.
- One-time links for other devices (Account) and for colleagues who lost access (Beheer).
- `python -m app.cli admin-link "Name"` / `join-link` for the server shell.
- Leaner UI: no custom fonts, no HTMX, no explanations; gzip; immutable static caching.
- Mail optional: `MAIL_BACKEND=none` hides email features.
- Fix: migrations were not committed once the SQLite foreign-key pragma was set.

- **Schema change: yes** (`7308e71681ff`: `users.email` nullable, `login_tokens.email`, `app_settings`).
  Rolling back to 0.1.0 needs a database restore.
- New secret keys: none (`SMTP_*`, `ADMIN_EMAILS` became optional).
- Manifest changes: `MAIL_BACKEND=none`, SMTP env vars commented out.

## 0.1.0 (2026-10-13)
First release: boards, first-come reactions, confirm, planning email, magic-link login.

- Schema change: initial schema (`d2df602710cd`).
- New secret keys: `SESSION_SECRET`, `PLANNING_EMAIL` (+ `SMTP_*`, `ADMIN_EMAILS` for mail).
- Manifest changes: initial manifests.
