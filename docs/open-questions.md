# Open questions

The app is built with a default for each question, so it can be piloted before they are all
answered. Changing a default is usually a config value or a small change.

| Question | Default in the app | How to change |
|---|---|---|
| Who may join? | **Invite list**: an admin adds name + email on `/beheer` (optionally sends an invite mail). No self sign-up. | An allow-list of domains would be a small change, but colleagues likely use private addresses. |
| Magic link OK? Session length? | Magic link (20 min, single use, needs a click). **90 days** logged in per device; "log out everywhere" on `/account`. | `SESSION_DAYS`, `LOGIN_LINK_MINUTES` |
| Notifications: email or push? | **Email** + in-app bell. Each person can turn the mails off. | Web push later (needs the site on the iPhone home screen). |
| Extra fields (event, location, dress code)? | None; the free-text **note** (200 chars) covers it. | Add columns + form fields. |
| Induction shifts (`I`)? | Swappable like any other type. | Remove `I` from `SHIFT_TYPES` in `app/shifts.py`. |
| Several shifts per person? Limits? | No limit on reacting. Max **30 open listings** per person (anti-spam). | `MAX_OPEN_LISTINGS` in `app/services.py` |
| Auto-accept the first reaction? | **No**: the owner always chooses (double confirmation). | Would be an option per listing. |
| Past listings / history? | Hidden from the boards the day after; completed swaps stay in "Mijn ruilen". Everything is **deleted 6 weeks** after the shift date. | `RETENTION_DAYS` |
| Who is admin? | Addresses in `ADMIN_EMAILS` (from OpenBao) + anyone they promote on `/beheer`. Admins can invite, block and promote. | |
| Planning read access? | **Only the emails**, as today. | A read-only planning account would be a later feature. |
| Name/branding | Neutral **"Ruilingen"**, no employer name or logo. | `APP_NAME` |

Still genuinely open (needs the owner):
- [ ] Which mail provider account (Resend assumed in `deploy/`) and the real planning address in OpenBao.
- [ ] Who are the first pilot colleagues and the first admins?
- [ ] Is anyone at work (department committee, planning) to be told before the pilot starts?
