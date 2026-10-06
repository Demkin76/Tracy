# Split deployment: Daytona UI + Ubuntu backend

Target authorized by the owner: `hzneznaju@109.245.66.196:22` (Ubuntu 24.04).
Application directory: `/home/hzneznaju/tracy-backend`.

Status on 2026-10-06: **abandoned and cleaned up at the owner's request**.
The staged application directory, four user units and temporary SSH key were
removed; linger was restored to its prior disabled state. No production database
was moved to this host. Production now runs on [AWS](../aws/README.md).
The instructions below describe the former proposal, not the live deployment.
`app.py` remains shared by AWS as the origin authentication wrapper.

The Cloudflare Worker keeps `tracys.online` as one origin. It sends `/v1/*`,
health and API documentation to `https://api-origin.tracys.online`; pages/assets
stay on the private Daytona preview. The backend binds only `127.0.0.1:8108`.
A dedicated named Cloudflare Tunnel connects that listener to Cloudflare.
The separate origin requires `X-Tracy-Origin-Token` on every request, including
health checks. The Worker removes any client-provided value and supplies its
secret binding. Normal sessions, CSRF and owner checks remain required.

`backend.static_app` is the frontend-only Daytona application. With
`POA_FRONTEND_ONLY=true`, it never opens a database/wallet or starts a worker.
This prevents the retained Daytona database from becoming a second writer.

## Services

User systemd units in this directory run as `hzneznaju`, with a private umask,
restart policies and resource limits. Linger must be enabled so they survive
logout and start at boot. Backend is limited to 1 GiB RAM and one CPU, tunnel
to 256 MiB. No unrelated nginx, Docker, ports or services are modified.

- `systemctl --user status tracy-backend tracy-tunnel`
- `systemctl --user restart tracy-backend`
- `journalctl --user -u tracy-backend --since '10 minutes ago'`
- `systemctl --user list-timers tracy-backup.timer`

`tracy-backup.timer` makes daily consistent, validated SQLite backups in
`~/tracy-backend/backups`, retaining 14. These are on the same host; configure
an independent destination for automated disaster recovery. The original
pre-migration copy remains in Daytona's separate backup volume.

## Migration requirements

1. Build and test code and the split-routing Worker before switching traffic.
2. Prepare source, locked dependencies, original production signing/wallet keys,
   origin token and systemd units. Keep local QA accounts out of production.
3. Verify tunnel TLS and the backend using an isolated preflight database.
4. Put API routes into maintenance mode. Switch Daytona to frontend-only and
   wait for the old worker to finish before making a final consistent backup.
5. Stream the validated backup directly into the authorized Ubuntu target;
   do not write production SQLite to the developer computer. Verify SHA-256,
   SQLite integrity and database signing/wallet identities before startup.
6. Start the backend, check authentication and real Binance/Devnet access, then
   switch the Worker API binding. Verify the public domain and API again.
7. Train and review the migrated BTC agent, start forward paper, verify its
   signed event chain, then stop the earlier local comparison.
8. Before rollback after new writes, preserve the newer database. Never blindly
   route users to Daytona's old snapshot. Maintenance plus a reverse migration
   is required to avoid losing new sessions/results.

Credentials and deployment evidence are ignored files in
`data/server-deployment/`; no tokens or private keys belong in the repository.
The one-off SSH key can be revoked by deleting its exact authorized_keys entry
with comment `tracy-deploy-20261006` after all remote verification is finished.
