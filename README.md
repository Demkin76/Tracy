# Tracy — AI trading agent marketplace with verifiable records

Tracy is marketplace first: discover public trading agents, compare their results and risk, and inspect the evidence behind each strategy version.

**User journey:** Marketplace → Compare agents → Inspect evidence → Test with personal limits → Review → Create a private paper instance → Monitor.

**Developer journey:** Developer studio → Prepare a strategy → Run evaluations and paper replay → Review publication → Publish an agent with its track record → Improve through versioned tests.

The homepage `/` is public discovery for both visitors and signed-in users. `/leaderboard` ranks eligible runs only within matching market periods, capital and cost assumptions; `/compare` exposes side-by-side settings and results. `/developers` manages publication and improvements; `/overview` is the personal workspace. The old `/explore` address redirects to `/`.

A public agent is an identity with a published, versioned strategy and its evidence. A personal instance has its own limits and execution history. No agent is created until the user acknowledges the tested configuration. Changing settings requires a new test. Deployment is atomic and repeat requests return the same agent. Publication remains an explicit, separate action.

## What works

- SOL/USDC, BTC/USDC and ETH/USDC candles from Binance Spot's public market-data endpoint, with 1h, 4h and 1d intervals. Every dataset is validated, timestamped, hashed and stored immutably. Provider failure returns an error; it never generates substitute prices.
- Three historical backtests and twelve executable boundary checks (inapplicable loss thresholds are labeled separately) through the execution policy evaluator. The following, separate 96-candle period is frozen for paper replay.
- Mean reversion, momentum and buy-and-hold templates; editable capital, fees, slippage, permissions, position limits, loss thresholds and human approval threshold.
- Paper execution, approval decisions, stop/pause controls, version history, measured PnL, degradation alerts and signed fill evidence bound to the recorded market data.
- A public agent marketplace, matched-condition paper leaderboard and side-by-side comparison, with a separate developer publication studio. Empty catalogs and insufficient samples remain empty; no ranking is invented.
- Separate workspace pages for strategy definitions, agent identities, guardrails, tests, monitoring, performance, alerts, proofs and account security. Public profiles are opt-in; the marketplace has no seeded listings.
- Accounts, owner isolation, CSRF protection, API keys, recovery codes, database backups and a single-worker HTTPS deployment configuration.

**Scope:** the AI-agent marketplace is the product direction; the current execution engine runs three supported deterministic templates, not arbitrary uploaded AI models. Prices are real; fills are simulated. Paper replay is a historical holdout, not forward live trading or exchange execution. Signals use prior closes and fills use the current close plus configured costs; no order-book/liquidity or intrabar execution model is claimed. Tests do not establish profitability. Loss thresholds stop new buys and do not guarantee a maximum loss on open holdings. Text extraction recognizes explicit settings and shows a diff; unmentioned settings remain labeled defaults. Copilot uses the same handbook as the website and can optionally connect to an AI provider. Only reviewed structured settings are enforced.

## Run locally

Python 3.12+ and Node 22+ are required. From the repository root:

```sh
uv sync --locked --extra dev --extra frameworks
npm --prefix frontend ci
npm --prefix frontend run build
uv run python -m scripts.setup_mvp
uv run python -m scripts.create_owner --email owner@example.com
uv run uvicorn backend.main:create_app --factory --host 127.0.0.1 --port 8000 --workers 1
```

The owner command prompts for a password. `setup_mvp` refuses to overwrite an existing `.env` and creates no sample records. Keep its private keys together with database backups. Open [Tracy](http://127.0.0.1:8000) to browse agents without signing in. Choose **Test with my limits** from a listing, or open **For developers** to prepare and publish your own agent. To run frontend development separately, use `npm --prefix frontend run dev`; Vite proxies `/v1` and `/v2` to port 8000.

Existing demo installations can keep their original database: `uv run python -m scripts.init_mvp --target data/tracy-mvp.sqlite3` creates a separate empty workspace retaining account credentials. Set `POA_DATABASE_PATH` to that target, `POA_DEVNET_ENABLED=false` and unused `POA_CONTROL_RESOURCES_PATH` / `POA_CONTROL_CREDENTIALS_PATH` paths. Restart and sign in again. Do not change signing keys for an existing database.

## Verification

```sh
uv run ruff check backend sdk scripts tests
uv run pytest -q
npm --prefix frontend run build
# Running local app required; this creates a private acceptance agent using actual exchange data:
uv run python -m scripts.check_market_live
# Playwright Chromium required; optionally set TRACY_BROWSER_PATH to an installed executable:
node frontend/qa-agent-builder.mjs
node frontend/qa-marketplace-first.mjs
node frontend/qa-navigation.mjs
node frontend/qa-copilot.mjs
# Optional isolated production-container check (Docker required):
docker build -t tracy:mvp-local .
uv run python -m scripts.check_container
```

Unit tests use an isolated deterministic provider transport so outages do not hide regressions. This transport exists only under `tests/`; users cannot select it. The separate live acceptance script fetches actual candles, runs the full lifecycle, recomputes/verifies the signed chain and saves `data/real-market-acceptance.json`. It uses `data/tracy-owner.json` for local credentials (email/password); do not commit this file. Browser onboarding QA creates a separate local QA account; navigation QA uses the same owner file. Reports and screenshots go under `data/`.

## Deploy and operate

See [DEPLOYMENT.md](DEPLOYMENT.md) for HTTPS deployment, initial accounts, health checks, backup and rollback. See [release verification](docs/RELEASE-CHECKS.md) for what was actually exercised locally and remaining deployment verification.

The API schema is at `/openapi.json`, interactive docs at `/docs`, health at `/healthz`, readiness at `/readyz`. Reviewed plans use `POST /v1/agent-plans` and `POST /v1/agent-plans/{id}/deploy` with the returned review hash and explicit acknowledgment.

Older Devnet payout and connector capabilities are documented in [CONTROL-LAYER.md](CONTROL-LAYER.md), [MARKETPLACE.md](MARKETPLACE.md) and the [legacy README](docs/LEGACY-README.md). Their demonstration scripts seed synthetic/example records and are **not** the paper MVP startup path. Devnet execution and local simulator adapters are disabled in production configuration. External integrations require operator-supplied resources and credentials.

Market-data reference: [Binance market-data-only API](https://github.com/binance/binance-spot-api-docs/blob/master/faqs/market_data_only.md), [Spot market-data endpoints](https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/rest-api/market).

## Copilot and the handbook

Every page has **Help for this page** and **Tracy Copilot**. `/help` contains chapters for intent, risk checks, exchange data, backtests, replay, metrics, health, publication, proofs and account privacy, with English and Russian explanations. The handbook is served from the same source used to ground Copilot answers.

Without a provider, the explicitly labeled built-in mode retrieves handbook explanations, recognizes supported English/Russian setting commands, proposes a diff and navigates to known sections. It is not an unrestricted AI conversation. Example: `Trade ETH/USDC with momentum, capital 2000 USDC, max position 200 USDC, max trade 100 USDC, daily loss 3%, approval above 80 USDC`. Ambiguous/unsupported instructions ask for clarification. Applying a proposal changes only a private draft; the user must test and review it again. It cannot execute, approve trades, deploy or publish. Deployed settings are edited through version creation.

To enable Gemini, set `POA_GEMINI_API_KEY` in the private `.env` / `.env.production` and restart. `POA_GEMINI_MODEL` defaults to `gemini-3.1-flash-lite`. `POA_COPILOT_PROVIDER=auto` prefers Gemini when its key is present; explicit choices are `gemini`, `openai`, or `reference`. The existing OpenAI integration uses `POA_COPILOT_API_KEY` and `POA_COPILOT_MODEL` (`gpt-4o-mini` by default). No automatic provider switch occurs after an error. Optional `POA_GEMINI_API_KEY_2` is a reserve for authentication failures; after a successful fallback it is preferred until restart. Keys in the same Google project share quotas: HTTP 429, capacity failures and timeouts do not trigger key rotation.

The UI names the active provider and requires opt-in before sending messages, recent conversation, draft settings and the authorized page summary. Keys/passwords and other owners' private records are not sent. Gemini's free tier has quotas and its data-use terms may allow submitted content to improve Google's products; the app does not enable billing or promise unlimited free use. See [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing) and [structured responses](https://ai.google.dev/gemini-api/docs/structured-output).

Both adapters use a restricted JSON schema and server-side validation. Gemini requests use the official Google endpoint with the API key in a server-side header, never a browser response or URL. Incomplete, blocked and invalid outputs leave settings unchanged; quota errors report a retry/reference-mode option. The existing OpenAI adapter uses `store: false`. No provider can directly execute, approve, deploy or publish.

Opt-in live acceptance: `uv run python -m scripts.check_copilot_live` against the running local app (uses `data/tracy-owner.json`). This sends three help/navigation/test-draft requests to Gemini and saves `data/gemini-acceptance.json`; no agent is created. Unit tests stub the provider and never consume the real key.

Publishing is available at the top of each strategy and from Developer studio or My strategies. The disclosure explains what becomes public. A marketplace visitor selects **Test this agent with my limits**, reviews a copy pinned to that source version and receives a fresh private identity and empty execution ledger. The data model currently retains a strategy copy per agent; it does not share mutable configurations between owners.
