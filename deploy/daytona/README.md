# Former Daytona deployment

Status (2026-10-06): **migrated to [AWS](../aws/README.md)**. The Tracy sandbox
and its separate backup volume were deleted after verified database migration,
public HTTPS/authentication checks, real market access and an S3 restore test.
The former Tier 1 outbound restrictions no longer block the strategy worker.

The tooling below documents the former deployment. Do not rerun `deploy.py` to
update AWS. `edge.mjs`, `deploy_edge.py`, `check_domain.py` and `launch_adaptive.py`
are still shared tools: AWS routing sends all paths to the AWS HTTPS origin and
does not use a Daytona preview token. Local owner recovery files stay private.

## Deployment tools and local recovery material

- Build `frontend/dist` using `npm run build` in `frontend` first.
- Run `deploy.py` with Python, the official `daytona` SDK, `python-dotenv` and `certifi`. It stages only an explicit source allowlist, creates/reuses the named sandbox and backup volume, and uploads production configuration separately from the image. Reusing an existing sandbox does not roll out application code updates.
- `runtime.py` is the image entrypoint. After configuration is uploaded it initializes the owner, drops to UID 10001, supervises one Uvicorn worker and schedules daily consistent backups. The S3 volume has fixed ownership: do not `chown` it or use it for live SQLite. When patching code with the SDK, restore readable file permissions before restarting; SDK uploads may create mode-0600 files.
- `python -m deploy.daytona.update` rolls out the built source to the existing sandbox without recreating it or changing credentials. It requires an identical dependency lock, verifies an off-sandbox backup, stops the single worker for the source replacement, resumes supervision and checks readiness/identity. It retains code for manual rollback; a failed health check requires inspection. Image-layer directory renames can fail with EXDEV, so rollback code is copied before source replacement. Production SQLite stays in Daytona.
- `python -m deploy.daytona.launch_adaptive` creates/reuses the cloud BTC momentum configuration and requests real historical training. It records a blocked data fetch honestly in `data/daytona-production/adaptive-launch.json`. After successful training, inspect the holdout report, explicitly activate a passing candidate through the API/UI, and record the reviewed revision before starting the 24-hour comparison. Reruns reuse an existing active forward run. No implicit real-money execution or copied local account database.
- Local recovery material is in ignored `data/daytona-production/`, with private configuration and owner credentials at mode 0600. Production uses the local owner's email and a newly generated password; see `owner.json`. Signing keys are in `production.env`. Preserve these separately from database backups.
- `check.py` refreshes the server-side preview token and checks HTTPS authentication/UI; `--skip-ai` avoids another Gemini request. Test evidence is saved alongside the recovery files. AI status 200 means an actual model reply, not merely configured credentials.
- `deploy_edge.py` publishes the Worker using Cloudflare's API, stores the preview token as a secret binding, and attaches the custom domain. Only the two identified GoDaddy parking A records may be replaced automatically; their original configuration is saved in `cloudflare-dns-before.json`. Other DNS records remain unchanged. Cloudflare now manages the apex DNS record for the Worker (the API represents it as AAAA `100::`; do not replace that with a Daytona IP).
- A sandbox stop/start may rotate its preview token. Run `check.py --skip-ai` to refresh local preview credentials, then `deploy_edge.py` to update the Worker secret, and `check_domain.py` to verify public traffic. Use a planned maintenance window; stale preview credentials interrupt access.

## Topology

`Browser → https://tracys.online (Cloudflare Worker + managed certificate) → Daytona HTTPS preview, port 8000 → Tracy`

Daytona's preview hostname is not a custom-domain certificate endpoint. A CNAME alone does not configure TLS for tracys.online. Cloudflare's Worker Custom Domain owns the external certificate and renews it. The connection from Worker to Daytona also uses HTTPS.

## Required account setup

1. Add `tracys.online` to Cloudflare, selecting the Free plan. Review imported records, preserving MX/TXT and other unrelated DNS records.
2. At GoDaddy, replace `ns09.domaincontrol.com` / `ns10.domaincontrol.com` with the exact two nameservers Cloudflare assigns. Do not invent the names or use a different account's nameservers. Wait for Cloudflare's zone to become Active.
3. Provide a scoped Cloudflare API token via the local ignored `.env`: `CLOUDFLARE_API_TOKEN`. Limit it to the deployment account and `tracys.online`; permissions needed for setup are Workers Scripts Edit, Workers Routes Edit, Zone Read and DNS Edit. Provide `CLOUDFLARE_ACCOUNT_ID` in the same file. No registrar password or Global API Key is needed.
4. The existing local `DAYTONA_API_KEY` / `DAYTONA_TARGET=eu` configure Daytona access. Do not copy the Daytona management key into the Worker or application image.

## Application deployment requirements

- Fresh production signing keys and a fresh private database; no local QA accounts or test agents should be uploaded automatically.
- `POA_ENVIRONMENT=production`, `POA_COOKIE_SECURE=true`, `POA_DEVNET_ENABLED=false`, `POA_SIGNUP_ENABLED=false`.
- `POA_CORS_ORIGINS=["https://tracys.online"]`; allowed hosts must contain `tracys.online`, `127.0.0.1`, `localhost` and the actual private Daytona preview hostname. The current Daytona proxy forwards `localhost` internally.
- One Uvicorn worker. Keep the SQLite database on the sandbox's persistent local filesystem. Daytona S3-backed volumes must not be assumed to provide SQLite WAL/file-lock semantics; use them only for completed consistent backup files after validation.
- For authorized 24/7 operation disable auto-stop/auto-pause as appropriate, auto-delete and wall-clock TTL. Configure supervised application restart on process failure and sandbox startup. Protect backups separately from the sandbox.
- Keep the sandbox private. Obtain the port-8000 preview origin and token using the SDK. That token is sandbox-wide; store it exclusively as Worker secret `DAYTONA_PREVIEW_TOKEN`. It can change after stop/start and must be refreshed in the Worker then.

## Edge configuration

`edge.mjs` forwards only to a configured port-8000 Daytona HTTPS origin. The EU SDK currently returns `8000-<sandbox-id>.daytonaproxy01.eu`; this hostname format and the documented `proxy.daytona.work(s)` format are allowed. It strips client-supplied Daytona/proxy headers, injects the private credential server-side, forwards sessions/CSRF headers, refuses unknown hosts, avoids caching and does not follow upstream redirects. `wrangler.jsonc` binds only `tracys.online`; www is not configured.

Set the actual `DAYTONA_ORIGIN` via Worker variables and `DAYTONA_PREVIEW_TOKEN` through Worker secrets before serving traffic. Never expose a preview token as a query string or public configuration. Publish the Worker with a Custom Domain only after the zone is Active. Resolve any existing conflicting apex DNS record deliberately, preserving all unrelated records.

Local check: `node --test deploy/daytona/edge.test.mjs`.

## Remaining release verification

- Domain/TLS/authentication checks have passed. Repeat `check_domain.py` after proxy or authentication changes.
- Unblock historical data fetch and run guardrail/backtest acceptance from the selected region. Gemini has returned a real answer, with an initial transient 503 followed by success.
- Keep consistent off-sandbox backups and the matching signing keys. Backup validation, application process restart and a full sandbox stop/start have passed. After full restart the owner can still log in, SQLite integrity is `ok`, and the API runs as UID 10001. Evidence is in `data/daytona-production/persistence-check.json` and `checks-without-ai.json`.

References:
- https://www.daytona.io/docs/en/custom-preview-proxy/
- https://www.daytona.io/docs/en/preview/
- https://www.daytona.io/docs/en/persistence/
- https://www.daytona.io/docs/en/network-limits/
- https://developers.cloudflare.com/workers/configuration/routing/custom-domains/
