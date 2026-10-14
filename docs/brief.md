# Original project brief

The brief this project started from (October 2026), kept for context. Several decisions have
changed since: login is by invite link with just a name (no email login), shift times are
required, the shift type is one label, and the planning email template is editable. The
current behaviour is described in [architecture.md](architecture.md).

## 1. The problem
The front-of-house staff (bar, cloakroom, champagne bar, programme sales, receptions) trade,
give away and take over shifts all the time. Today this happens in a WhatsApp group:
- Messages get lost in the chat; it's unclear what is still available
- "Who was first?" is argued over; people experiment with polls to decide
- There's no overview of what's offered and what's wanted

## 2. What the portal is (and isn't)
- **It is** a peer tool among colleagues: a clear, shared board of offered and wanted shifts.
- **It isn't** the official planning system. Planning/administration keep working exactly as now:
  they receive **one email** saying who takes over whose shift, and enter it in their own system.
  The portal only makes that email consistent and saves the chaos before it.
- So the portal does **not** enforce labour rules, qualifications or approval. Planning still does.

## 3. Core flow
1. **Aangeboden** (offered): a colleague posts a shift they want to give away (date, start, end,
   shift type, optional note). Listings are shown **oldest first**, with the exact **time posted**
   and a rank (#1, #2, ...).
2. **Gezocht** (wanted): a colleague posts that they're looking for a shift on a date, with the
   shift types they'd accept.
3. Anyone can react to **any** listing. Order is visible, but you're **not** limited to the first.
   - On an offered shift: "Ik neem deze dienst" (I'll take it).
   - On a wanted request: "Ik heb een dienst voor je", entering the shift you offer (time + type).
4. The owner of the listing sees all reactions, **in order of who was first**, and **chooses** one
   ("Bevestigen" / confirm). Reacting + confirming = **double confirmation**.
5. The listing closes; other reactions expire and those people are notified.
6. The portal shows a **ready-made email to planning**: To = planning, Cc = both colleagues,
   subject + body from a template. **The colleague sends it from their own mail app**
   (mailto/copy). The portal does not send it: planning then gets it from a colleague, exactly as
   today, and there are no spam/deliverability or "who is this app" issues.
7. Notifications (someone reacted, you were chosen, your reaction expired) go by email (and maybe
   push later).

Edge cases to handle: two people react at the same moment (first-come must be correct, no double
accept); withdrawing a reaction; removing a listing; listings in the past disappear.

## 4. Shift types
Letters, in the **order they happen within the shift**:

| Code | Meaning |
|---|---|
| `H` | Horeca: behind a bar |
| `G` | Garderobe: cloakroom |
| `C` | Champagne: a special kind of bar |
| `P` | Programma's: selling programmes |
| `R` | Receptie: formal reception, varied tasks |
| `I` | Inwerkdienst: induction shift (exact format unknown, ask) |

Known combinations: `H, HG, GH, G, CGH, CHG, CH, R, PH, PHG, PGH` (+ induction).
`HG` = bar first, cloakroom after the break. `CGH` = champagne, then cloakroom, then bar.

## 5. Email template (to planning)
```
Aan:       <planning address>
Cc:        <giver>, <taker>
Onderwerp: Dienstruil <date> · <type> <start>–<end>

Beste planning,

<taker> neemt de volgende dienst over van <giver>:

  Datum:  <weekday day month> (<YYYY-MM-DD>)
  Tijd:   <start>–<end>
  Soort:  <type> (<expanded meaning>)

Wij hebben dit allebei bevestigd.

Met vriendelijke groet,
<giver> en <taker>
```
The real planning address is known to the owner but deliberately **not** in this public repo;
make it a config value.

## 6. Prototype
[`prototype.html`](prototype.html): a working clickable demo (single HTML file, vanilla
JS, open in a browser). It has 8 made-up colleagues, a "Ik ben" (I am) switcher to play both
sides, the two boards, reactions with order, confirm, a notification panel, and the generated
planning email. State lives in `localStorage` only. Treat it as the **UX reference** for the real
build: the flow, wording and shift-code chips are what the owner showed/wants.

## 7. Recommended stack
Chosen for being simple, debuggable by the owner, and overlapping with their upcoming job
project (a FastAPI platform):
- **FastAPI** (Python) + **Jinja2** server-rendered templates + **HTMX** for interactivity
  (no separate JS build)
- **SQLite** (one file; plenty for a group of colleagues). SQLAlchemy/SQLModel + Alembic migrations
- Login via a **group join link + name** (email optional), sessions in a signed cookie
- Optional outgoing email (notifications only) via a transactional mail service free tier
  (e.g. Brevo or Resend). **Not** from the homelab itself (it would land in spam).
- Dutch UI; code and repo in English

Alternatives considered: SvelteKit + SQLite (nice DX, but a new framework), Next.js + Postgres
(too heavy for this).

## 8. Hosting and deployment
Live at **https://ruilingen.app** on the owner's home Kubernetes cluster (k3s): Flux GitOps,
Cloudflare Tunnel, Longhorn volume (nightly backups) for the SQLite file, OpenBao + External
Secrets for secrets.

**Deploys are release-only:** `git tag vX.Y.Z && git push origin vX.Y.Z` → CI pushes image
`X.Y.Z` → Flux image automation bumps the homelab repo and deploys it. Pushes to `main` build
images but don't deploy. The runtime contract, secrets and release checklist are in
[`deploy/README.md`](deploy/README.md); release notes in [`CHANGELOG.md`](CHANGELOG.md).

Be honest with users that this is a **pilot on a home server**: if it's down, they fall back to
WhatsApp.

## 9. Privacy and ground rules
- Personal data of colleagues: name, email, listed shifts. Store **nothing more**, delete old
  data (e.g. swaps older than X weeks), let people delete their account.
- This repo must **never** contain real names, email addresses, schedules or the employer's
  name/branding. Use made-up example data only (as in the prototype).
- It's an informal tool among colleagues; tell the people involved what's stored and why.
- Access must be restricted (the site is public on the internet): invite list or allowed email
  addresses, not open sign-up.
