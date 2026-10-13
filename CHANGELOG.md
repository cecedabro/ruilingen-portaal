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

## 0.4.0 (2026-10-13)
- Light/dark switch in the header, remembered per device (cookie); light stays the default.
- Posting time removed from the boards (the #n posting order stays).
- "Wanneer" filter is now a week calendar (monday–sunday) with selectable days, from today up
  to the end of the latest published rooster (published tuesdays for the week after), or the
  furthest posted shift if later. Each day shows how many shifts it has.

- Schema change: none (rollback = just pin the previous image tag)
- New secret keys: none
- Manifest changes: none. Optional env `ROSTER_RELEASE_WEEKDAY` (default 1 = tuesday).

## 0.3.0 (2026-10-13)
- Shifts: only date + type required; optional time or dagdeel, zaal, werkplek, opmerking.
- Shift type shown as a single label; bottom tab bar on phones; light theme only for now.
- New look: navy header, teal accent, boards grouped by date with the time on the left,
  zaal/werkplek/opmerking written out.
- Filters: soort, deze/volgende week, dagdeel, zaal, nog vrij / al gereageerd.
- Posting order stays visible: every shift shows #n (who posted first, over the whole board),
  and "Volgorde: Eerst geplaatst" lists the board oldest-posting first.
- Shifts someone already reacted to show "1 reactie · wacht op …"; others can still react
  as backup ("Reageer als 2e") and see their place in line.

- **Schema change: yes** (`73538935c3ff`: adds `listings.daypart/hall/workplace`,
  `reactions.offer_daypart/offer_hall/offer_workplace`; add-column only). Rolling back to 0.2.0
  needs a database restore.
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
