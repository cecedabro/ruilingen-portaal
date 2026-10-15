# Changelog

Releases are deployed automatically when the `vX.Y.Z` tag is pushed (see
[deploy/README.md](deploy/README.md)). Every release lists these three, even when the answer is
"none", because they decide whether a deploy or rollback needs manual work:

- **Schema change**: migrations run at start and only go forward. If yes, a rollback also needs
  a database restore (Longhorn backup from before the release).
- **New secret keys**: must be in OpenBao `ruilingen/app` *before* the release, or the pod won't start.
- **Manifest changes**: must be made in the homelab repo (`apps/ruilingen/`) as well.

## Unreleased
- Swaps (ruilen): when giving a shift away you choose Weggeven, Ruilen or Allebei, and can say
  what you'd like back (date range, types; optional). Others propose a swap with "Ruil
  voorstellen": type in the shift they give back, or pick one of their own offered shifts
  (which is taken down when the swap is confirmed). Proposals outside the wish are allowed
  and get a "buiten je wens" note. The orange "ruil" / "ruil of weg" label shows it on the board.
- Completed swaps show both shifts on Mijn, and the email to planning lists both (own,
  admin-editable template for swaps).
- The "vandaag/morgen" label is gone from the shift cards.
- The demo data now includes swap offers and proposals.

- **Schema change: yes** (`aeb3cc50550f`: `listings.mode/want_from/want_to/want_types`,
  `reactions.offer_date/offer_listing_id`; existing rows become "give" and earlier replies get
  their date). Rolling back to 0.8.0 needs a database restore.
- New secret keys: none
- Manifest changes: none

## 0.8.0 (2026-10-14)
- New compact shift cards: day first (bold), start–end time smaller next to it, type on the
  right; #rank, name, vandaag/morgen and reaction status on the second line. Tap a card to
  open zaal/werkplek/opmerking and the actions. On Mijn, shifts that need you open by
  themselves.
- Notification mail only for "someone reacted to your shift" (one on/off switch on Account);
  clearer mail text with a direct link. Everything else stays in the bell.
- Demo data for the pilot: made-up colleagues and shifts (`python -m app.cli demo-seed`),
  removable with one button on Beheer ("Demo-data verwijderen") or `demo-remove`.
- deploy/README.md: step-by-step mail setup.

- Schema change: none. Rollback = pin the previous image tag.
- New secret keys: none (mail stays off until SMTP_USERNAME/SMTP_PASSWORD are added).
- Manifest changes: none

## 0.7.0 (2026-10-14)
- Date shown inside every shift card (calendar tile) with the time next to it, plus
  "vandaag"/"morgen"; no more separate day headings. Overall styling pass: white cards on a
  soft background, aligned zaal/werkplek/opmerking, consistent spacing, quieter admin links.
- The planning email template is editable by admins on Beheer (placeholders like `{gever}`,
  `{nemer}`, `{details}`; "Standaard terugzetten" restores the default). "Mail naar planning"
  opens it in your own mail app.
- Code restructured: `app/services/` (rules per area) and `app/web/` (session, rendering,
  routes per area); tests split per area. New docs: docs/architecture.md, docs/database.md,
  CONTRIBUTING.md; the original brief moved to docs/brief.md.
- Repository: CODEOWNERS; `main` and release tags protected (only the owner merges and tags).

- Schema change: none (the template is stored in the existing `app_settings` table).
  Rollback = pin the previous image tag.
- New secret keys: none
- Manifest changes: none

## 0.6.0 (2026-10-14)
- Invite links: the main group-chat link (the existing one keeps working) plus extra links
  admins create with an optional expiry and use limit, revocable; admin invite links are always
  single-use and valid 24 hours. Beheer shows how often each link was used.
- Members on Beheer: promote/demote, one-time login link, delete (account and all its data;
  people who reacted to their open shifts are notified). "Block" is gone.
- Admins can delete any open offer or request; the poster and reactors are notified.
- The last admin can't be demoted or deleted.
- No more email login (and no `ADMIN_EMAILS` bootstrap): joining is only through invite links.
  Email stays optional, verified, and only for notifications; verifying doesn't log in.

- **Schema change: yes** (`7e500a3621ae`: new `invite_links` table; the group link's code moves
  from `app_settings` into it). Rolling back to 0.5.0 needs a database restore.
- New secret keys: none (`ADMIN_EMAILS` is no longer read)
- Manifest changes: none

## 0.5.0 (2026-10-14)
- Instant navigation: the four tabs are prefetched and links swap the page in place (no
  reload); full page loads cross-fade (view transitions). Weggeven/Zoeken switches in place.
- Clearer active tab in the bottom bar (tinted pill, bold label, indicator).
- Offers (and shifts offered in reply) require type, date, begin and end time.
- Zaal and werkplek are fixed choices from lists admins edit on Beheer (stored in the database,
  not in this public repo; generic defaults until set).
- Shift type "I" is now "Inwerk".
- iOS Safari: date/time inputs no longer overflow on narrow screens.

- **Schema change: data only** (`410c76a25636` renames shift type `I` → `Inwerk` in existing
  rows). Rolling back to 0.4.0 needs a database restore (0.4.0 doesn't know "Inwerk").
- New secret keys: none
- Manifest changes: none. After deploy, set the real lists once on Beheer (or
  `python -m app.cli set-list halls "...;..."`).

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
