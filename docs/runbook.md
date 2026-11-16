# Runbook: when something goes wrong

Calm first: Ruilingen being down means colleagues swap the old way for a while. Nobody misses a
shift because of it. The one thing worth protecting is the data, and that has three layers:

| Layer | How often | Kept | Where | Covers |
|---|---|---|---|---|
| App copies (`/data/backups`) | hourly + at every start | 48 | same volume | bugs, mistakes |
| Longhorn backup | nightly 02:00 | 7 | NAS | volume / node loss |
| Off-site copy | nightly 05:00 | | Backblaze B2 (encrypted) | house / NAS loss |

Commands below assume `kubectl --context homelab`, and
`POD=$(kubectl -n ruilingen get pod -l app=ruilingen -o name)`.

## 1. "The site is down" (uptime alert, or colleagues tell you)

1. Post the fallback message (below) so nobody waits on you.
2. `curl -sS https://ruilingen.app/healthz`. A Cloudflare error page means the tunnel or the
   house is down; a slow or 5xx answer means the app.
3. `kubectl -n ruilingen get pods` and `kubectl -n ruilingen logs deploy/ruilingen --tail=100`.
4. Just released? Go to 2. Cluster/house down and not coming back today? See the emergency plan
   (not built yet). Otherwise fix it when you can: a few hours down is fine.

## 2. A release broke something

Roll forward to the old code: `git revert <commit>`, add a CHANGELOG entry, tag a new patch
version (`vX.Y.Z+1`). Flux deploys it like any release. Don't move or delete existing tags.

If the broken release had a **schema change**, the old code can't run on the new schema: restore
the `ruilingen-…-voor-migratie.db` copy the pod made just before migrating (section 3, then
release the revert). Writes since the release are lost; the Longhorn backup is the fallback.

## 3. Data got damaged (bug, wrong click)

1. See what's there and pick the last good hour (times are Europe/Amsterdam):
   `kubectl -n ruilingen exec deploy/ruilingen -- python -m app.cli backups`
2. Optionally inspect it locally first:
   `kubectl -n ruilingen cp ${POD#pod/}:/data/backups/ruilingen-YYYYMMDD-HHMMSS.db ./check.db`
   and open with `sqlite3 check.db`.
3. Stop the app. Flux would scale it straight back up, so suspend it first
   (`flux get kustomizations` shows the name):
   `flux suspend kustomization <name>` then
   `kubectl -n ruilingen scale deploy/ruilingen --replicas=0`
4. Swap the file with a temporary pod that mounts the volume:
   ```bash
   kubectl -n ruilingen run restore --rm -it --restart=Never --image=busybox:1.37 \
     --overrides='{"spec":{"securityContext":{"runAsUser":10001,"runAsGroup":10001},
       "volumes":[{"name":"data","persistentVolumeClaim":{"claimName":"ruilingen-data"}}],
       "containers":[{"name":"restore","image":"busybox:1.37","stdin":true,"tty":true,
       "command":["sh"],"volumeMounts":[{"name":"data","mountPath":"/data"}]}]}}'
   # inside:
   cd /data && mkdir -p broken && mv ruilingen.db* broken/
   cp backups/ruilingen-YYYYMMDD-HHMMSS.db ruilingen.db && exit
   ```
5. Start again: `kubectl -n ruilingen scale deploy/ruilingen --replicas=1` and
   `flux resume kustomization <name>`. Check `/healthz` and the board.
6. Everything since that hour is gone: tell colleagues to check their swaps from after it.
   Delete `/data/broken` later, once you're sure.

Before something risky (a big Beheer change, a migration), take an extra copy:
`kubectl -n ruilingen exec deploy/ruilingen -- python -m app.cli backup`

## 4. Practise once

Do section 3 once on a quiet evening with a copy from a minute ago, and time it. After that it's
a chore, not a crisis.

## Messages to colleagues

Down:
> Ruilingen is even niet bereikbaar. Ruil zolang zoals vroeger (via de groep / planning). Ik
> laat het weten als het weer werkt.

Back:
> Ruilingen werkt weer. Ruilingen die je in de tussentijd anders hebt geregeld hoef je er niet
> alsnog in te zetten.

Data restored:
> Ruilingen is teruggezet naar [tijd]. Heb je daarna iets geplaatst of bevestigd? Kijk even of
> het er nog staat en zet het anders opnieuw.
