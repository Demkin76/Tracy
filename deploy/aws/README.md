# Tracy on AWS

Production migrated on 2026-10-06. Website, API, SQLite and the paper worker run
on one EC2 instance in **eu-north-1**, AWS CLI profile **tracy**. Cloudflare remains
the domain/HTTPS edge. There is no running Daytona dependency.

## Topology and resources

`Browser → https://tracys.online → Cloudflare Worker → HTTPS aws-origin.tracys.online → Caddy → 127.0.0.1:8108 → Tracy`

- CloudFormation stack: `tracy-production`; source: `stack.json`.
- EC2: `i-07fc6aa78ff1eb66d`, Ubuntu 24.04, t3.small, 2 GiB RAM.
- Elastic IP: `16.171.107.253`; DNS-only A record `aws-origin.tracys.online`.
- Root disk: 20 GiB encrypted gp3. IMDSv2 required. No inbound SSH or API port.
- Private, encrypted, versioned S3: `tracy-production-322758218105-eu-north-1`.
- Configuration: SSM SecureString `/tracy/production/config` → root:tracy 0640 `.env`.
- The instance role can read its configuration/release and read/write its backups.
- Application runs as `tracy` with one Uvicorn worker, restart on failure and boot.
- Caddy automatically obtains and renews the origin certificate. Cloudflare
  manages the public certificate. The Worker strips caller-supplied origin
  credentials, supplies its secret, and routes every application path to AWS.
- Direct origin requests without the secret receive 403. Session auth and CSRF
  are still enforced. Secrets are never included in frontend assets.
- CloudTrail and an EC2 status alarm exist. The alarm has no notification target;
  external uptime notifications have not been configured.

The recorded EC2 on-demand rate at deployment was $0.0216/hour (about $15.77 for
730 hours), before disk, public IPv4, monitoring, storage and traffic. CPU credits
use standard mode. The project was on Free plan with $100 credit at setup;
check AWS Settings → Billing for current spend/plan and credit expiry. This is a
single-server MVP, not a highly available deployment.

## Operation

Use AWS Systems Manager Run Command (`AWS-RunShellScript`) with profile `tracy`
and region `eu-north-1`. `control.py` wraps the CLI without printing secrets.
On the instance:

```sh
systemctl status tracy caddy tracy-backup.timer
systemctl restart tracy
journalctl -u tracy --since '10 minutes ago'
systemctl start tracy-backup.service
journalctl -u tracy-backup -n 10
```

Application directory: `/opt/tracy`; database: `/opt/tracy/data/tracy.sqlite3`.
Do not print `.env` or SecureString values. Production owner credentials remain
in the local ignored `data/daytona-production/owner.json`; the migration kept
the same user/password and signing/wallet identities. Signup remains closed.
Toolkit/MCP setup is installed for Codex and Cursor; restart the application to
load newly registered MCP servers. The CLI already works with `--profile tracy`.

## Releases

Build `frontend/dist` and run relevant checks. Stage the explicit allowlist from
`deploy.daytona.deploy.image_context`, plus `deploy/server` (origin gate) and
`deploy/aws`; exclude caches, `.env`, `data` and `.git`. Upload this source tarball
to `release/current.tar.gz` in the private bucket. Source packages contain no
credentials or databases. `install-release.sh` installs locked dependencies,
SSM configuration and units; it does not restore or overwrite the database.
The release currently in S3 includes the corrected unprivileged-venv permissions.

Before an update, run and verify the backup service, retain the previous release
object version, stop the single app worker, install the release and start Tracy.
Check public readiness, auth, assets and active forward runs. A long interruption
can invalidate a forward sample; the engine records missing data rather than
inventing trades. Do not restore an old database over a newer active run.

Cloudflare configuration is still maintained by `deploy/daytona/deploy_edge.py`.
With `data/aws-deployment/routing.json` enabled, it uses only AWS origin bindings,
not Daytona preview credentials. `deploy.daytona.check_domain` verifies the
public domain, SSL, UI assets, session auth, CSRF and paper-only capabilities.

## Backups and recovery

The daily systemd timer creates a consistent SQLite snapshot, validates receipt
chains/market hashes, uploads it to S3, independently downloads it and verifies
SHA-256 and SQLite integrity. Keep 14 local backups and 30 days in S3. Daily
backups can lose up to a day's changes after complete disk loss. Original signing
and wallet seeds in SSM must accompany any restored database; do not regenerate.

For recovery, stop Tracy and preserve the current database plus WAL/SHM before
replacement. Download a chosen S3 snapshot into a **new path**, validate it with
`scripts.backup.validate`, and restore with the matching original configuration.
Check database identity, owner login and signed adaptive reports/forward events
before switching traffic. Restore into a fresh data directory so stale WAL/SHM
cannot be paired with the backup. Keep old data until validation passes.

CloudFormation retains the S3 bucket and root volume, and the instance has
termination protection. Deleting the stack alone is not a complete cleanup.
Deliberately preserve or remove retained data only after a recovery decision.

## Migration evidence and running experiment

Private evidence is under `data/aws-deployment/`. Production SQLite was streamed
from quiesced Daytona directly to private S3 without saving it on the Mac.
SHA-256 matched; original owner, agent and cryptographic identities were retained.
Public TLS/auth/CSRF, Binance bid/ask, Solana Devnet, and S3 restore checks passed.
The old Ubuntu staging installation/key and Daytona sandbox/backup volume were
removed. Historical deployment files remain as documentation and shared tooling.

- Agent: `/lab/adaptive_5a4a3bd9ad7e488987cbade19b30c269`.
- Forward: `/lab/forward/forward_1b1a682473dc471d98ec7e65d552ec4c`.
- Bundle: `/bundles/bundle_b2bd6afe7b47403f831c5a5af3994cbd`.
- Scheduled comparison: 2026-10-06 17:49:45 to 2026-10-07 17:49:45 Europe/Belgrade.
- BTC/USDC, hourly candles, $1,000 virtual capital per arm, real Binance quotes,
  configured fees/slippage. Baseline 60 bps vs reviewed adaptive entry 90 bps.
- Holdout: baseline -$8.365596, candidate -$6.846627. All five activation checks
  passed, but both returns were negative. Reduced historical loss is not profit.
- Bundle hash confirmed by a Solana **Devnet** memo. This establishes a timestamped
  hash, not exchange execution or profitability. No real funds or mainnet trades.

The earlier local comparison was stopped and its final event chain verified.
