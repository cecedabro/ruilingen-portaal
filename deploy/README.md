# Deployment

**Live** at https://ruilingen.app, on the k3s homelab, deployed by Flux.

- **Live manifests:** [`cecedabro/homelab`](https://github.com/cecedabro/homelab) →
  `apps/ruilingen/` and `apps/network-policies/ruilingen.yaml`.
- **`deploy/homelab/` here is only a reference copy** of those. Changing it deploys nothing; the
  homelab repo has to be changed separately (see [Manifest changes](#manifest-changes)).

## How a release reaches the cluster

```
git tag vX.Y.Z && git push origin vX.Y.Z
   │
   ▼  GitHub Actions (.github/workflows/ci.yml): tests, then builds + pushes
ghcr.io/cecedabro/ruilingen-portaal:X.Y.Z   (also :X.Y and :latest)
   │
   ▼  Flux ImageRepository scans ghcr every 5 min; ImagePolicy picks the newest ^X.Y.Z$ (semver >= 0.1.0)
Flux ImageUpdateAutomation commits the new tag to cecedabro/homelab (author: fluxcdbot)
   │
   ▼  normal Flux sync
namespace ruilingen: pod recreated → migrations run → app starts
```

- **Deploys are release-only.** Pushes to `main` build images (`main-<timestamp>-<sha>`,
  `main`, `sha-<sha>`) but do **not** deploy. Only a full `X.Y.Z` image tag does.
- Expect the new version live within ~5–10 minutes of the image appearing.
- Renovate is disabled for this image; Flux image automation does the bump.
- Flux config: `homelab/apps/flux/image-automation.yaml`.

### Releasing
1. Make sure `main` is green in CI.
2. Write the release notes in [`CHANGELOG.md`](../CHANGELOG.md). Call out explicitly:
   - **schema change** (rollback then needs a database restore, see below)
   - **new secret key** (must be in OpenBao *before* the release, see below)
   - **manifest change** (new env var, port, probe, volume, ...)
3. Tag and push:
   ```bash
   git tag v0.3.0 && git push origin v0.3.0
   ```
4. Check: `kubectl -n ruilingen get pods` and https://ruilingen.app/healthz → `ok`.

### Rollback
Pin the previous tag in `homelab/apps/ruilingen/deployment.yaml` (and suspend the
ImageUpdateAutomation, or Flux bumps it back to the newest release). Migrations only go
forward: **if the bad release changed the schema, also restore the database** from the
Longhorn backup (nightly, 7 kept) taken before it. The [changelog](../CHANGELOG.md) says which
releases changed the schema.

## Runtime contract
Things the cluster relies on. Changing any of them is a manifest change.

| What | Value |
|---|---|
| Replicas / strategy | exactly **1**, **Recreate** (SQLite on a RWO Longhorn volume) |
| Port | **8000** (Service `ruilingen` :80 → 8000) |
| Health | `GET /healthz` → 200 `ok`, **no auth** (readiness + liveness probes, Homepage status dot) |
| User / filesystem | non-root **UID 10001**, **read-only root filesystem**; only `/data` (PVC) and `/tmp` (emptyDir) writable |
| Database | `sqlite:////data/ruilingen.db`; migrations run at container start, forward only |
| Proxy | Cloudflare tunnel: plain HTTP from cloudflared with `X-Forwarded-Proto/For`. The entrypoint keeps `--proxy-headers --forwarded-allow-ips='*'`, so `request.client.host` is the real client IP (from `X-Forwarded-For`); use that for any per-IP rate limiting |
| `BASE_URL` | `https://ruilingen.app` |
| `MAIL_BACKEND` | `none` (for now) |

### Secrets
From OpenBao `secret/ruilingen/app` via External Secrets (`envFrom` the `ruilingen-app` Secret).

| Key | Status |
|---|---|
| `SESSION_SECRET` | set. Never rotate casually: it logs everyone out, and people without an email can only get back in with an admin-made link |
| `PLANNING_EMAIL` | set |
| `SMTP_USERNAME`, `SMTP_PASSWORD` | not set; only needed once mail is enabled |

**A new required secret key must be added in OpenBao before the release that needs it**, or the
pod fails to start. Say so in the release notes.

## Manifest changes
When a release needs one (new env var, new secret key, different port/probe, ...):
1. Update `deploy/homelab/` here, in the same PR as the code.
2. Mention it in the release notes.
3. Make the same change in the homelab repo **before or with** the release. Keep the Flux marker
   on the image line: `image: ghcr.io/cecedabro/ruilingen-portaal:X.Y.Z # {"$imagepolicy": "flux-system:ruilingen"}`

## Operations
- **First admin / lost admin access** (no mail needed):
  ```bash
  kubectl -n ruilingen exec deploy/ruilingen -- python -m app.cli admin-link "Your Name"
  ```
  prints a one-time login link (60 min).
- **Join link** for the group chat: on the Beheer page, or
  `kubectl -n ruilingen exec deploy/ruilingen -- python -m app.cli join-link`.
- **Logs:** `kubectl -n ruilingen logs deploy/ruilingen`.
- **Restart:** `kubectl -n ruilingen delete pod -l app=ruilingen`.
- **Backups:** the PVC is in Longhorn's default group: nightly backup to the NAS, 7 kept.
- **Database peek:** the image has no `sqlite3` CLI; use
  `kubectl -n ruilingen exec deploy/ruilingen -- python -c "import sqlite3; ..."`.
  For real surgery, scale to 0 and work on a copy.

## Enabling notification mail

Optional. When on, colleagues can add an email address on Account (confirmed with a link)
and then get **one kind of mail: "someone reacted to your shift"**. Everything else stays in
the bell. No app release is needed; it's configuration only.

1. **Resend** (or any SMTP provider): create an account at resend.com, then *Domains → Add
   domain* → `ruilingen.app`, region EU.
2. **DNS:** Resend shows 3–4 records (an MX and TXT for `send.ruilingen.app`, a DKIM TXT
   `resend._domainkey`). Add them in Cloudflare DNS for `ruilingen.app` as **DNS only** (grey
   cloud). Also add DMARC: `_dmarc` TXT `v=DMARC1; p=quarantine;`. Wait until Resend says
   *Verified* (usually minutes).
3. **API key:** Resend → *API Keys → Create*, permission *Sending access*, domain
   `ruilingen.app`.
4. **OpenBao** `secret/ruilingen/app`: add `SMTP_USERNAME` = `resend` and `SMTP_PASSWORD` =
   the API key. Then force the sync:
   `kubectl -n ruilingen annotate externalsecret ruilingen-app force-sync=$(date +%s) --overwrite`
5. **Homelab** `apps/ruilingen/deployment.yaml` (keep the `$imagepolicy` marker line as is):
   ```yaml
   - name: MAIL_BACKEND
     value: smtp
   - name: MAIL_FROM
     value: Ruilingen <noreply@ruilingen.app>
   - name: SMTP_HOST
     value: smtp.resend.com
   - name: SMTP_PORT
     value: "587"
   ```
   Commit; Flux restarts the pod with mail on (do step 4 first, or the mail settings are
   empty).
6. **Check:** on Account an email field appears; add your own address, confirm it, and let
   someone react to a test shift. Errors show in `kubectl -n ruilingen logs deploy/ruilingen`.

Turning it off again: `MAIL_BACKEND=none`.
