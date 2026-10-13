# Ruilingen Portaal

A website where colleagues at a concert hall swap shifts with each other, replacing a chaotic
WhatsApp group chat. Planned domain: **ruilingen.app**.

> This README is the full project brief, written to be handed to a developer (or an AI coding
> session) that starts from zero. Everything decided so far, and everything still open, is here.

---

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
[`demo/prototype.html`](demo/prototype.html): a working clickable demo (single HTML file, vanilla
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
- Login via **magic link** (email link, no passwords), sessions in a signed cookie
- Outgoing email (magic links + notifications) via a transactional mail service free tier
  (e.g. Brevo or Resend). **Not** from the homelab itself (it would land in spam).
- Dutch UI; code and repo in English

Alternatives considered: SvelteKit + SQLite (nice DX, but a new framework), Next.js + Postgres
(too heavy for this).

## 8. Hosting and deployment
Pilot runs on the owner's home Kubernetes cluster (k3s), which already has:
- **Flux** GitOps (apps are HelmReleases/manifests in a separate homelab repo)
- **Cloudflare Tunnel** for public access (no open ports at home), Cloudflare DNS
- **Longhorn** volumes with nightly backups (an SQLite file on a PVC is covered)
- **OpenBao + External Secrets Operator** for secrets (mail API key, session secret)
- **Renovate** for dependency updates, **ntfy** for alerts

Plan: GitHub Actions builds a container image → `ghcr.io/cecedabro/ruilingen-portaal` → deployed
by Flux in the homelab → public at **ruilingen.app** through the Cloudflare tunnel.
Note: `.app` domains are HTTPS-only (HSTS preloaded); Cloudflare handles the certificate at the
edge, so that's fine.

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

## 10. Status and next steps
- [x] Clickable prototype (demo for the department committee)
- [ ] Owner answers the open questions below
- [ ] Scaffold FastAPI app (models, magic-link login, the two boards, reactions, confirm, email draft)
- [ ] Mail service account + domain `ruilingen.app` (owner buys it, about €8/year)
- [ ] Dockerfile + GitHub Actions → ghcr.io
- [ ] Deploy to the homelab via Flux + Cloudflare tunnel
- [ ] Pilot with a few colleagues

## 11. Open questions
See [`docs/open-questions.md`](docs/open-questions.md).
