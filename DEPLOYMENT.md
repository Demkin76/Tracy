# Deploy the paper MVP

This deployment serves recorded-market backtests and historical paper replay. It does not connect a funded exchange account, send exchange orders, provide live forward paper trading or host an LLM. Optional Copilot uses an operator-configured external AI API; see the README for configuration and data disclosure. Start with invited users and monitor resource usage: SQLite and one worker are intentional MVP limits.

## Fresh HTTPS installation

Use a Linux host with Docker Engine and Compose v2, a hostname pointing to it, and inbound TCP 80/443 (UDP 443 is optional). The host needs HTTPS access to Binance's public market-data endpoint. Availability is subject to the provider's network/geographic restrictions; failed requests produce an explicit error. Do not silently change the price source.

From a checkout on the host:

```sh
python3 -m scripts.setup_mvp --domain tracy.your-domain.com
# Review .env.production locally. Never post or commit the generated seeds.
docker compose --env-file .env.production -f compose.production.yaml config --quiet
docker compose --env-file .env.production -f compose.production.yaml build
docker compose --env-file .env.production -f compose.production.yaml run --rm tracy /app/.venv/bin/python -m scripts.create_owner --email owner@your-domain.com
docker compose --env-file .env.production -f compose.production.yaml up -d
```

`create_owner` prompts for a password. Signup is closed by default; run the same account command to invite another user. Owner means ownership of that user's workspace, not access to everyone else's data. Signing seeds must stay stable for a database. `setup_mvp` refuses to overwrite an existing environment file.

The app runs as a non-root user, with a read-only image, a persistent data volume, a temporary `/tmp`, a 256 KiB request limit, secure session cookies and explicit allowed hosts. Only Caddy exposes network ports. One Uvicorn worker is enforced by a process lock; do not scale replicas against the same SQLite file. `.env.production` is required at deployment time and is not baked into the image.

Caddy obtains and renews HTTPS certificates when DNS and ports are correct. See [automatic HTTPS](https://caddyserver.com/docs/automatic-https) and [reverse proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy). The application base images are pinned to the digests used in the local build. Pin the tested Caddy digest in your release process before rollout; its supplied major-version tag receives upstream changes.

## Release checks on the target host

```sh
docker compose --env-file .env.production -f compose.production.yaml ps
docker compose --env-file .env.production -f compose.production.yaml logs --tail 100 tracy caddy
curl --fail https://tracy.your-domain.com/healthz
curl --fail https://tracy.your-domain.com/readyz
```

Readiness checks database access, migrations and built frontend assets; it deliberately does not claim that an external price provider is available. Log in through HTTPS, create a reviewed plan, check the displayed source/dates, deploy paper mode, advance the replay and verify its proofs. Check approvals, pause/stop and sign-out with a separate invited account. Confirm unknown hosts are rejected and the app port is not public. Set up external uptime monitoring, log retention and disk alerts on your hosting platform.

Local evidence is recorded in [RELEASE-CHECKS.md](docs/RELEASE-CHECKS.md). Successful local tests do not establish that DNS, TLS or a container works on an untested host. No public deployment has been performed by this change.

## Back up and restore

Make a consistent online backup and validate receipt chains and market-data hashes:

```sh
docker compose --env-file .env.production -f compose.production.yaml exec tracy /app/.venv/bin/python -m scripts.backup --out /app/data/backups/release-before-update.sqlite3
docker compose --env-file .env.production -f compose.production.yaml cp tracy:/app/data/backups/release-before-update.sqlite3 ./release-before-update.sqlite3
```

Choose a new filename for each backup; the tool refuses overwrites. Copy backups off the host with restricted access and retain the matching `.env.production` seeds separately. They contain account data and must not be public. A backup inside the same Docker volume alone is not disaster recovery.

Restore into a **new volume**, with the app stopped and matching original signing keys. Put the validated SQLite backup at `/app/data/tracy.sqlite3` owned by UID/GID 10001; point a Compose override at the new volume. Keep the original volume intact until the restored app and proof verification pass. Do not copy a running SQLite main file without its WAL; use the backup command instead. Never use `docker compose down --volumes` during an update.

Before upgrades, retain the previous image digest, back up the database and keys, then build the new image and start one instance. Check readiness and the browser flow. For rollback after migrations, use the previous image with the pre-upgrade backup in a separate volume; migrations are not promised to be reversible.

## Existing local demo data

The local MVP uses a separate `data/tracy-mvp.sqlite3`. Original demo records remain in their original database and in `data/backups/pre-real-data.sqlite3`. Account credentials were retained; historical demo sessions were not. Do not publish the demo database or its known credentials. The MVP configuration disables Devnet and does not load simulator resources.

External HTTP/GitHub/SQL connectors remain optional operator integrations. Add only actual configured resources and server-side credentials after testing their permissions and independent readback contract. No connector is enabled by seeding an example. Exchange execution requires a separate broker adapter and account authorization; adding API keys alone does not turn historical replay into live trading.
