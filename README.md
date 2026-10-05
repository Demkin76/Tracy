# Tracy 3.0 — exchange & lifecycle infrastructure for AI trading agents

Test → Prove → Deploy → Monitor → Detect degradation → Adapt.

Versioned strategies, reproducible backtests, controlled paper execution, signed Trading Proofs, performance accounting, backtest/live gap, transparent Strategy Health, regime context, alerts and a risk-aware agent exchange.

**Run:** `.\Start-TracyV3.ps1 -SkipBuild` (omit SkipBuild on a fresh checkout). Open http://127.0.0.1:8000/ or the exchange at http://127.0.0.1:8000/explore. Local login is in data/tracy-owner.json.

- [Product and operator guide](TRACY-V3.md)
- [60–90 second demo script](DEMO-V3-90SEC.md)
- [Acceptance checks and scope](TRACY-V3-ACCEPTANCE.md)

Current trading execution uses synthetic paper replay. Proofs explicitly report `on_chain: false`; no Jupiter/Solana swap fill is claimed. Native SOL Devnet execution and the complete v1/v2 infrastructure remain available under Guardrails / Infrastructure. Trading publication does not publish original action histories.

## Preserved v2 control layer

Tracy sits between an agent and sensitive actions: signed intent → task/policy check → optional human approval → controlled execution → independent readback → signed receipt.

The primary application is **/control**. Built-in adapters cover native SOL on Devnet, fixed SQLite inserts, GitHub draft pull requests and an HTTP operation/readback contract. Provider credentials remain server-side. API, Python SDK, MCP stdio and LangChain tools are included.

**Start the prepared local demo:** ` .\Start-ControlDemo.ps1 -SkipBuild ` (omit SkipBuild on a fresh checkout). Add `-NewScenario` for fresh approval requests. Open http://127.0.0.1:8000/control. Local credentials: data/tracy-owner.json. GitHub and paid API examples use a local simulator and do not create real PRs or spend money.

Read [CONTROL-LAYER.md](CONTROL-LAYER.md) for setup, policies, SDK/MCP, receipt verification, adapter contracts and deployment boundaries. [DEMO-CONTROL-1MIN.md](DEMO-CONTROL-1MIN.md) is the one-minute operator script.

Enforcement requires agent/runtime isolation and exclusive server custody of the protected credentials. `protect` wraps tools; it is not an OS sandbox or an automatic interceptor of arbitrary code. SPL/USDC and swaps require additional adapters. This is a runnable control-layer release, not a claim of universal integrations or production security certification.

## Preserved v1 capabilities

The directory, hosted Devnet payout recipes and original receipts remain available.

## Choose and run an agent

Open /explore, inspect a profile, choose **Use agent**, configure recipients and spending limits,
and install a private instance. Open **Installed agents** to run once, start a bounded schedule,
stop execution, or inspect each run's signed receipts. Installation itself sends no funds.

Two hosted recipes are supported: ordered batch payouts and scheduled payouts.
Instances have separate keys, policies and histories. Author edits do not alter an installed recipe.
The platform runs these deterministic recipes; it does not download an external author's bot code.
Test funds come from the shared Devnet sponsor wallet, with instance, owner and platform limits.

Authors can enable a versioned runnable offer in their agent settings.
A listed, active profile with an enabled offer displays Use agent.
For the prepared local Atlas and Sentinel profiles: python -m scripts.enable_marketplace_demo.

See [MARKETPLACE.md](MARKETPLACE.md) for the user journey, section guide and runtime guarantees.

## Implemented

- Account signup, login, logout and persistent cookie sessions.
- Owner isolation for agents, settings, actions, history and receipts.
- My agents: create, name, description, public key, active/stopped, daily usage.
- Versioned policies: allowed recipients/actions, transfer limit, daily budget.
- Atomic budget reservation and a second stop/policy check before dispatch.
- Personal API keys, revocation, 30-day expiry; Python SDK, CLI and a standalone payout bot.
- Existing real Devnet transfer, RPC verification, signed receipts, hash chains, JSON export and browser WebCrypto verification.

- Public agent directory, category/search/sort, profiles, side-by-side comparison and watchlists.
- Transparent reliability metrics with explicit sample sizes and a Wilson lower bound.
- Opt-in publication of complete receipt histories; expiring, revocable links for individual proofs.
- Cross-agent history with server-side filters, pagination, CSV, analytics and notifications.
- Automatic PENDING reconciliation with backoff; OS lock prevents multiple workers using the same database.
- Account recovery codes, password changes, read-only API keys and security activity.
- Account and platform sponsor quotas, funding view, backup/restore tooling, container configuration and CI.

See [PRODUCT.md](PRODUCT.md) for the Russian product guide and release acceptance details.
This release supports the complete choose/configure/run/verify path for those two Devnet recipes.
It has no real-money commerce, mainnet execution or arbitrary hosted AI-agent programs.

## Run locally

Windows PowerShell, from the project root. Requires Python 3.12+, Node.js 22+ and uv.

~~~powershell
uv sync --locked --extra dev
# Only on a new checkout, when .env does not exist:
.\.venv\Scripts\python.exe -m scripts.setup_demo
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run build
.\.venv\Scripts\python.exe -m uvicorn backend.main:create_app --factory --host 127.0.0.1 --port 8000 --workers 1
~~~

Open the [public catalog](http://127.0.0.1:8000/explore) or [your workspace](http://127.0.0.1:8000) and create an account. [API documentation](http://127.0.0.1:8000/docs).

On the prepared demo machine: **owner@tracy.local**, password in **data/tracy-owner.json**. That file contains credentials and is excluded from Git. Preserve .env with the database: the signing key and execution wallet are pinned to its identity.

To assign existing MVP agents to the local owner, stop the server first:
~~~powershell
.\.venv\Scripts\python.exe -m scripts.bootstrap_owner
~~~
Only unowned agents are assigned. Existing receipt bodies and keys are preserved. There is no public HTTP endpoint to claim legacy agents.

Development frontend: npm.cmd --prefix frontend run dev. Vite proxies /v1 to the backend. Browser signing requires a secure context, including localhost or HTTPS.

## Try the product

1. **My agents → Create agent**: name, description, browser demo key, recipient, per-transfer limit and daily budget.
2. **Run signed action**: submit 0.01 SOL to the allowed recipient.
3. Open its receipt → **Verify receipt** to check signatures, hash, chain and fresh RPC evidence.
4. Submit an amount within the per-transfer limit but beyond the remaining daily budget: REJECTED / daily_budget_exceeded.
5. **Manage agent → Stop agent**: a new signed request produces REJECTED / agent_stopped.
6. Edit the policy: a new version is appended; existing receipts keep their original snapshots.
7. **Connect SDK**: issue and revoke a personal API key.

A browser demo private key lives only in its current tab. Reloading, signing out or creating another demo agent ends that signing session. Saved history remains accessible. Use the SDK for persistent agents. Public-page navigation within the same tab preserves the browser signing session.

## SDK and standalone bot

Create a personal API key in **Connect SDK** and copy it once. It manages your account. A separate Ed25519 private seed signs the agent's actions.

~~~powershell
$env:TRACY_API_KEY = "YOUR_PERSONAL_API_KEY"
.\.venv\Scripts\python.exe -m sdk.poa init --key-file data/my-agent.json --name "Payout bot" --recipient RECIPIENT_ADDRESS --limit 0.1 --daily-budget 1
.\.venv\Scripts\python.exe -m sdk.poa transfer --key-file data/my-agent.json --to RECIPIENT_ADDRESS --amount 0.01 --request-id payout_001
~~~

Replace RECIPIENT_ADDRESS with a public Devnet recipient address. init saves keys before registration; reruns preserve the key and return the existing agent. Changed init arguments do not edit an existing policy; use the workspace or update_policy.

CLI transfer uses payout: the same request ID and parameters return the saved operation; PENDING is reconciled without another broadcast. Conflicting parameters under the same ID fail. **A new ID creates a new operation. After a lost response, retry the same ID.**

Copy examples/payout-jobs.json into data/jobs.json and replace its recipient:
~~~powershell
.\.venv\Scripts\python.exe -m scripts.payout_bot --key-file data/my-agent.json --jobs data/jobs.json
~~~

Each job contains request_id, to and amount. Keep job IDs stable across restarts. Run the bot again to reconcile PENDING jobs. The example has no scheduler or built-in LLM.

~~~python
import json, os
from sdk.poa import PoAClient

keys = json.load(open("data/my-agent.json"))
with PoAClient(api_key=os.environ["TRACY_API_KEY"]) as tracy:
    result = tracy.payout(
        keys["private_seed"], keys["agent_id"], recipient, 0.01,
        request_id="payout_001",
    )
    print(result["status"])
    if result["receipt_id"]:
        print(tracy.verify(result["receipt_id"]))
~~~

The lower-level transfer method submits once and raises HTTP 409 for replay. Use payout for restartable jobs. SDK reads TRACY_API_KEY; CLI also reads TRACY_URL.

To bring your own key: python -m sdk.poa keygen --key-file data/existing-agent.json. Enter the printed **agent_id and public_key** in **Use my SDK public key**. Never paste the private seed. Store key files under ignored data/.

## Policy semantics

- Per-agent limits, integer lamports; network fees are separate.
- The UTC day is assigned on admission. No cron is needed for rollover.
- VERIFIED counts against its admission day. PENDING/PREPARING reserve funds, including across a day boundary while unresolved.
- REJECTED, proven transaction failure and proven non-submission release reservations. MISMATCH conservatively remains charged to its admission day.
- Lowering a limit does not reset spending; new transfers need sufficient remaining budget.
- Stop blocks new dispatches, including requests awaiting RPC preparation. A PENDING transaction cannot be recalled.
- A policy edit during preparation rejects that request as policy_changed_before_submission. Review the new policy before issuing a new request ID.
- Receipts sign the policy snapshot, version and decision context. Prior daily usage is a gateway attestation, not an independent proof of complete history.

## Authentication and API

Passwords use salted PBKDF2-SHA256 with 600,000 iterations. Cookie sessions use HttpOnly and SameSite=Strict. Cookie-authenticated writes require X-CSRF-Token from signup/login/me; Origin validation and login throttling are enabled. Sessions last seven days by default.

Workspace endpoints accept a cookie session or Authorization: Bearer PERSONAL_API_KEY. Personal keys have manage or read-only access and expire after 30 days. Read-only keys cannot issue keys, edit policies or mutate workspace state. Only hashes of session/API tokens are stored. Recovery codes are also hashed, shown once and consumed atomically. Changing or recovering a password revokes all sessions and API keys. The old shared POA_ADMIN_TOKEN is never accepted.

| Method | Endpoint | Purpose |
|---|---|---|
| POST | /v1/auth/signup, /v1/auth/login | Account/session |
| GET / POST | /v1/auth/me, /v1/auth/logout | Restore/logout |
| GET / POST | /v1/account/api-keys | List/issue |
| DELETE | /v1/account/api-keys/{id} | Revoke |
| GET / POST | /v1/agents | My agents/register |
| GET / PATCH | /v1/agents/{id} | Detail/name/description |
| POST | /v1/agents/{id}/status | active boolean |
| PUT | /v1/agents/{id}/policy | expected_version and policy |
| GET | /v1/agents/{id}/policy/versions | Immutable versions |
| GET | /v1/agents/{id}/actions | History, counts, limit/offset |
| GET | /v1/agents/{id}/requests/{request_id} | Resume a job |
| POST | /v1/actions | Agent Ed25519 authentication; no owner cookie needed |
| GET | /v1/actions/{id} | State and receipt |
| POST | /v1/actions/{id}/reconcile | Read RPC again; never resubmit |
| GET | /v1/receipts/{id} | Receipt |
| GET | /v1/receipts/{id}/verify | Fresh verification |
| GET | /v1/receipts/{id}/chain | Chain export |
| GET | /v1/config, /v1/health | Public config/RPC health |

Other owners' resources return 404; missing/expired authentication returns 401. Revoking an API key does not invalidate an agent's separate signing key: **use Stop agent to block its actions**.

## Protocol

RFC 8785 canonical JSON; Ed25519 signs request_id, agent_id, action, params and timestamp. Amount is a JSON number, positive, at most 1,000,000 SOL with at most nine fractional digits. Strings, booleans and fractional lamports fail validation.

The receipt hash is SHA-256 of canonical body excluding receipt_hash and poa_signature. The signature covers the raw 32 digest bytes. Each agent has sequence and previous_receipt_hash. Receipt insertion and terminal state are one SQLite transaction; update/delete triggers protect receipts and policy versions.

System transfer plus Memo containing the unsigned request hash binds the on-chain action to its intent. Verification independently reads getTransaction and checks network, signer, fee payer, recipient, amount, instructions, memo and actual balance changes.

VERIFIED means the exact transfer was confirmed; REJECTED is a signed pre-execution refusal; FAILED is an error; PENDING remains unresolved. RPC unavailability never produces valid=true. Browser WebCrypto verifies crypto locally; the backend reads fresh blockchain evidence.

Offline JSON verification:
~~~powershell
.\.venv\Scripts\python.exe -m scripts.verify_receipt receipt.json --public-key TRUSTED_BASE64_KEY --chain chain.json
~~~
Obtain the trusted key independently. Offline checks cryptography, not the blockchain.

## Validation

~~~powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check backend sdk scripts tests
npm.cmd --prefix frontend run build
Push-Location frontend
node qa-week1.mjs
Pop-Location
~~~

Normal browser QA creates a separate account and policy rejections, spending no SOL. Requires Chrome, running backend, and data/presentation-recipient.json with public_key of your Devnet recipient. Reports/screenshots: data/qa-week1/.

Real test-fund checks:
- python -m scripts.week1_live_check: separate CLI/bot processes, 0.001 SOL and restart without duplication; data/week1-sdk-report.json. Requires local owner and recipient files.
- From frontend: node present-demo.mjs. Opens Chrome, creates a demo agent, spends 0.01 SOL, checks daily rejection/Stop and keeps the window open.
- python -m scripts.live_smoke: requires TRACY_API_KEY; creates an agent and spends 0.01 SOL. --airdrop permits one faucet request.

## Scope and operating limits

Use POA_COOKIE_SECURE=true behind HTTPS; false is for local HTTP. .env.example lists configuration.

One worker, one SQLite database, a shared Devnet execution wallet. Do not run multiple server processes against the same database: startup recovery of PREPARING assumes a single worker. PENDING is reconciled automatically in the background with backoff up to 300 seconds, and may also be checked by users/SDK. Reconciliation never resubmits a transfer.

This is a local release using test funds. All accounts use the same execution wallet. External multi-user deployment still needs separate funding/quotas, execution-key management, queues and monitoring. Email is an account identifier; email delivery/verification is not configured. Self-service recovery uses a saved one-time recovery code.

Commitment is confirmed, not finalized. RPC/gateway honesty remains an assumption: signed attestations with on-chain evidence, not TEE/trustless proofs. A chain without external checkpoints cannot prove absence of a hidden tail.

No mainnet, paid marketplace, arbitrary actions, custom Solana contract or built-in LLM. Public execution metrics are not an intelligence or profitability rating.

References: [Solana getTransaction](https://solana.com/docs/rpc/http/gettransaction), [OWASP password storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html), [OWASP CSRF](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html).

## Platform API additions

- GET /v1/public/agents: q, category, sort (recent / verified / reliability), limit, offset.
- GET /v1/public/agents/{id} and /receipts: public profile and complete published history.
- GET /v1/public/receipts/{id}, /verify, /chain: public proof and independent checks.
- PUT /v1/agents/{id}/publication: listed, category, tagline, disclose_history.
- POST /v1/shares: receipt_id, expires_days (1-30), disclose_receipt. GET /v1/shares; DELETE /v1/shares/{id}.
- GET /v1/public/proofs/{share_id} and /verify: one scoped proof, no private predecessor disclosure.
- GET /v1/favorites; PUT/DELETE /v1/favorites/{agent_id}.
- GET /v1/history and /export: agent_id, status, q, since, until, limit, offset. Export rejects filters exceeding 10,000 rows.
- GET /v1/analytics?days=30 (1-90), /notifications, /funding, /runtime.
- POST /v1/notifications/read.
- PATCH /v1/account/profile; POST /v1/account/password, /recovery-code; GET /v1/account/events.
- POST /v1/auth/recover: email, recovery_code, new_password.
- GET /healthz: local process/database liveness, independent of external RPC availability.

Public verification is limited to 120 requests per IP per 15 minutes. Mutation bodies larger than 256 KiB are rejected when their declared Content-Length exceeds the limit. Put a reverse proxy body/rate limit in front of any Internet-facing deployment.

SDK additions: history, publish (explicit disclose_history), unpublish, share (explicit disclose_receipt), revoke_share, catalog, public_agent and verify_shared.

## Operation and backup

Default sponsor limits: 1 SOL per owner/day and 5 SOL platform/day, excluding fees. All admission/reservation checks run in one SQLite write transaction. POA_EXECUTION_ENABLED=false pauses new dispatches while confirmations continue.

~~~
POA_RECONCILER_ENABLED=true
POA_RECONCILIATION_INTERVAL_SECONDS=5
POA_OWNER_DAILY_LAMPORTS=1000000000
POA_PLATFORM_DAILY_LAMPORTS=5000000000
POA_EXECUTION_ENABLED=true
~~~

Run locally with ./Start-Tracy.ps1, or ./Start-Tracy.ps1 -SkipBuild after an existing build.

Consistent backup of the running database, validating signed receipts:
~~~powershell
.\.venv\Scripts\python.exe -m scripts.backup --out data/backups/release.sqlite3
# Restore drill into a NEW file; existing files are never overwritten:
.\.venv\Scripts\python.exe -m scripts.backup --source data/backups/release.sqlite3 --out data/restored.sqlite3
~~~
Back up the matching .env secrets separately. To switch databases, stop Tracy, set POA_DATABASE_PATH to the restored file, and restart with the matching original signing/execution seeds. Do not overwrite a live database or delete its WAL files.

Container:
~~~sh
docker compose config --quiet
docker compose up --build -d
docker compose logs --tail=100 tracy
~~~
The image runs as an unprivileged user with a read-only root filesystem. Its named data volume is separate from the host data directory; existing host history is not copied automatically. Compose binds only 127.0.0.1:8000. For Internet hosting, terminate HTTPS at your chosen reverse proxy, set POA_COOKIE_SECURE=true, configure trusted proxy handling and exact CORS origins, and preserve the data volume and secrets.

CI runs Python tests/lint and the frontend build. Container configuration has been parsed locally; an image build requires a running Docker daemon.

## Full acceptance checks

~~~powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check backend sdk scripts tests
npm.cmd --prefix frontend run build
Push-Location frontend
node qa-platform.mjs
Pop-Location
.\.venv\Scripts\python.exe -m scripts.prepare_platform_demo
~~~

The platform browser test covers guest/owner publication, cryptographic verification, comparison, watchlist, history export, analytics, notifications, share revocation, unpublishing and one-time account recovery. Its requests are rejected by policy, so it spends no SOL.

prepare_platform_demo creates two clearly labeled sample agents and six real transfers of 0.000001 Devnet SOL, plus three policy refusals. It saves keys and stable job IDs; reruns reuse those operations. It publishes only these demonstration agents, not existing private agents. It also creates a seven-day proof link. Reports: data/qa-platform/report.json and data/platform-demo-report.json.

Methodology: [NIST Wilson confidence intervals](https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm). A minimum of five settled attempts is a Tracy display threshold, not a guarantee of statistical independence or future performance.

## Managed runtime and acceptance

Schema v4 adds versioned offers, private installations and durable run queues without modifying receipts.
The existing reconciliation worker advances managed payouts. Keep POA_RECONCILER_ENABLED=true
for automatic execution. Run exactly one worker per database.
A cancelled in-flight transfer may still settle; Stop prevents subsequent dispatch.
Failed or rejected rows stop the batch and schedule. A new manual run repeats the complete plan.

The marketplace integration tests cover owner isolation, request deduplication, policy budgets,
bounded schedules, restart recovery, stop races, CSRF and read-only access, and graceful shutdown.
Run: python -m pytest tests/test_marketplace.py -q.
Browser acceptance: cd frontend; node qa-marketplace.mjs.
This creates an isolated test account and spends three micro-transfers of 0.000001 Devnet SOL plus fees.
Reports and desktop/mobile screenshots are saved under data/qa-marketplace.
Use TRACY_QA_OWNER=1 only when intentionally preparing examples in the local owner's account.
