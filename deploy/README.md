# Deploying to the homelab

The app runs on the k3s homelab (repo `cecedabro/homelab`), deployed by Flux, public at
**https://ruilingen.app** through the existing Cloudflare tunnel.

```
git tag v0.1.0 ─► GitHub Actions ─► ghcr.io/cecedabro/ruilingen-portaal:0.1.0
                                              │
homelab repo: apps/ruilingen/deployment.yaml ─┘ (image tag) ─► Flux ─► namespace ruilingen
                                                                          │ Service :80
Cloudflare tunnel: ruilingen.app ─► http://ruilingen.ruilingen.svc.cluster.local ─┘
```

`deploy/homelab/` mirrors the homelab repo layout: copy `apps/ruilingen/` and
`apps/network-policies/ruilingen.yaml` into it as is.

## One-time setup

### 1. Domain in Cloudflare
`ruilingen.app` must be a zone in the same Cloudflare account as the tunnel: add the site in
Cloudflare (Free plan) and set the registrar's nameservers to the two Cloudflare gives you.
`.app` is HSTS-preloaded (HTTPS only); Cloudflare's edge certificate covers that.

Recommended zone settings: SSL/TLS → Edge Certificates → **Always Use HTTPS** on.
Optional: Security → WAF → a rate-limiting rule on `/login` (e.g. 10 requests/minute per IP).
The app already limits login mails per address.

### 2. Mail provider (optional, can be done later)
Without mail, everything works: people join with just their name via the group link. Mail
adds optional email notifications and email login. The app speaks plain SMTP, so any provider works. The manifests assume **Resend**
(free: 3,000 mails/month, 100/day). For Brevo instead, set `SMTP_HOST=smtp-relay.brevo.com`.

1. Create an account, add the domain `ruilingen.app`.
2. Add the DNS records it shows (SPF `TXT`, DKIM `TXT`/`CNAME`, and a return-path `MX` on a
   subdomain) in Cloudflare DNS, **DNS-only** (grey cloud). Wait until the provider says "verified".
3. Add a DMARC record: `_dmarc.ruilingen.app TXT "v=DMARC1; p=quarantine; rua=mailto:<you>"`.
4. Create an API key with "sending access" only. That is the SMTP password (username `resend`).

### 3. Secrets in OpenBao
In the OpenBao UI create `secret/ruilingen/app` with these keys:

| Key | Value |
|---|---|
| `SESSION_SECRET` | `openssl rand -hex 32` (required) |
| `PLANNING_EMAIL` | the real planning address |
| `SMTP_USERNAME` | only with mail: `resend` |
| `SMTP_PASSWORD` | only with mail: the Resend API key |
| `ADMIN_EMAILS` | only with mail: your address (made admin at startup) |

### 4. Container image
```bash
git tag v0.1.0 && git push origin v0.1.0
```
Image: `ghcr.io/cecedabro/ruilingen-portaal` (public, inherits the repo's visibility).

| Tag | When | Use |
|---|---|---|
| `0.2.0`, `0.2`, `latest` | `git tag v0.2.0` | pinned releases (Renovate) |
| `main-<YYYYMMDDHHmmss>-<sha>` | every push to `main` | Flux image automation (sortable) |
| `main`, `sha-<sha>` | every push to `main` | manual testing |

Flux image automation (needs the image-reflector + image-automation controllers):
```yaml
apiVersion: image.toolkit.fluxcd.io/v1beta2
kind: ImageRepository
metadata: {name: ruilingen, namespace: flux-system}
spec: {image: ghcr.io/cecedabro/ruilingen-portaal, interval: 5m}
---
apiVersion: image.toolkit.fluxcd.io/v1beta2
kind: ImagePolicy
metadata: {name: ruilingen, namespace: flux-system}
spec:
  imageRepositoryRef: {name: ruilingen}
  filterTags: {pattern: '^main-(?P<ts>[0-9]+)-[a-f0-9]+$', extract: '$ts'}
  policy: {numerical: {order: asc}}
```
and mark the image line in `deployment.yaml` with
`# {"$imagepolicy": "flux-system:ruilingen"}` plus an `ImageUpdateAutomation` that commits to
the homelab repo.

### 5. Homelab repo
1. Copy `deploy/homelab/apps/ruilingen/` → `homelab/apps/ruilingen/` and
   `deploy/homelab/apps/network-policies/ruilingen.yaml` → `homelab/apps/network-policies/`.
2. Add to `homelab/apps/kustomization.yaml`:
   ```yaml
     # secrets plumbing
     - ruilingen/externalsecret.yaml
     # workloads not managed by Helm
     - ruilingen/namespace.yaml
     - ruilingen/pvc.yaml
     - ruilingen/deployment.yaml
     # network policies
     - network-policies/ruilingen.yaml
   ```
   (`namespace.yaml` must come before the others; kustomize orders Namespaces first anyway.)
3. Add a Renovate rule to `homelab/renovate.json` so a new app release is proposed right away
   instead of on Saturday:
   ```json
   {
     "description": "Own app: deploy new releases straight away",
     "matchPackageNames": ["ghcr.io/cecedabro/ruilingen-portaal"],
     "schedule": ["at any time"],
     "automerge": true
   }
   ```
   Leave `automerge` out if you'd rather click merge yourself.
4. Commit + push. Check: `kubectl -n ruilingen get pods,externalsecret,pvc`.

### 6. Tunnel route
Cloudflare Zero Trust → Networks → Tunnels → `k3s-homelab` → Public hostnames → Add:
- Hostname: `ruilingen.app` (no subdomain)
- Service: `HTTP` → `ruilingen.ruilingen.svc.cluster.local:80`

Then open https://ruilingen.app/healthz → `ok`.

### 7. First admin and the join link
No mail needed:
```bash
kubectl -n ruilingen exec deploy/ruilingen -- python -m app.cli admin-link "Your Name"
```
prints a one-time link (60 min). Open it on your phone: you're logged in as admin. On
**Beheer** you'll find the **join link** to post in the WhatsApp group (also:
`python -m app.cli join-link`). If it leaks, "Nieuwe link" there invalidates the old one.
Someone lost their phone? Beheer → their name → **Inloglink**, send it to them privately.

## Releasing a new version
```bash
git tag v0.2.0 && git push origin v0.2.0
```
CI tests, builds and pushes `:0.2.0`; Renovate opens (and with automerge, merges) the bump in the
homelab repo; Flux rolls it out. Migrations run automatically at container start.
Rollback: set the previous tag in `homelab/apps/ruilingen/deployment.yaml`. Note: migrations
don't run backwards, so for a release with a schema change, restore the Longhorn backup too.

## Operations
- Logs: `kubectl -n ruilingen logs deploy/ruilingen` (mail errors show up here).
- Database shell (read-only peek):
  `kubectl -n ruilingen exec -it deploy/ruilingen -- python -c "import sqlite3; ..."`.
  The image has no `sqlite3` CLI on purpose. For real surgery, scale to 0 and work on a copy.
- Backups: the volume is in Longhorn's default group → nightly backup to the NAS (7 kept).
- Restart: `kubectl -n ruilingen delete pod -l app=ruilingen` (plain manifest, see homelab ops
  notes on why not `rollout restart`).
- If the home server is down the site is down: colleagues fall back to the WhatsApp group.
  Consider an uptime check (e.g. ntfy + a free external monitor on `/healthz`).
