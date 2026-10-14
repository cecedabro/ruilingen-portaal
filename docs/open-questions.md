# Open questions

The app is built with a default for each question, so it can be piloted before they are all
answered. Changing a default is usually a config value or a small change.

| Question | Default in the app | How to change |
|---|---|---|
| Who may join? | Anyone with the **join link** from the group chat, with just a name (unique). Admins can rotate the link and block people. | |
| Login? Session length? | Name only, no email or password. Logged in for **1 year** per device, renewed on every visit. Other devices via a one-time link. Email optional (verified). | `SESSION_DAYS`, `LOGIN_LINK_MINUTES` |
| Notifications: email or push? | In-app bell for everyone; **email** for those who added an address (can be turned off). | Web push later (needs the site on the iPhone home screen). |
| Extra fields (event, location, dress code)? | None; the free-text **note** (200 chars) covers it. | Add columns + form fields. |
| Induction shifts (`I`)? | Swappable like any other type. | Remove `I` from `SHIFT_TYPES` in `app/shifts.py`. |
| Several shifts per person? Limits? | No limit on reacting. Max **30 open listings** per person (anti-spam). | `MAX_OPEN_LISTINGS` in `app/services.py` |
| Auto-accept the first reaction? | **No**: the owner always chooses (double confirmation). | Would be an option per listing. |
| Past listings / history? | Hidden from the boards the day after; completed swaps stay in "Mijn ruilen". Everything is **deleted 6 weeks** after the shift date. | `RETENTION_DAYS` |
| Who is admin? | The first admin via `python -m app.cli admin-link`; then admins promote members or send a single-use admin link from Beheer. Admins manage links and members, and can delete shifts. | |
| Planning read access? | **Only the emails**, as today. | A read-only planning account would be a later feature. |
| Name/branding | Neutral **"Ruilingen"**, no employer name or logo. | `APP_NAME` |

Still genuinely open (needs the owner):
- [ ] Mail provider (optional; Resend assumed in `deploy/`) and the real planning address in OpenBao.
- [ ] Who are the first pilot colleagues and the first admins?
- [ ] Is anyone at work (department committee, planning) to be told before the pilot starts?
