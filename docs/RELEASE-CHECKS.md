# Local MVP verification — 2026-10-05

These checks were executed against the local implementation, not a public deployment.

| Check | Result |
|---|---|
| Python suite | 175 passed; one upstream Starlette/AnyIO deprecation warning on Python 3.14 |
| Ruff | Passed for backend, SDK, scripts and tests |
| TypeScript + Vite production build | Passed |
| Real exchange acceptance | Passed: Binance SOL/USDC, three historical test periods, separate 96-candle paper replay, two signed fills |
| Proof checks | Signature, chain, ledger readback and pinned market-data match passed; no on-chain claim |
| Copilot and publication | Passed: text extraction, preview-before-apply, contextual guide, Russian replies, navigation, mobile panel, real source export, 12 policy scenarios, 3 saved tests and fresh marketplace copy |
| Browser creation flow | Passed: no early agent creation, test invalidation, review acknowledgment, private deployment, saved review, mobile layout |
| Browser navigation | Passed: 12 distinct sidebar sections, 49 internal links; no JavaScript errors or failed application API requests |
| Owner isolation | Tests and pending approvals from another account stay hidden |
| Backup verification | Consistent SQLite backup validated with two signed trading receipts and immutable market-data hashes |
| Production Compose configuration | Static validation passed without resolving a production secrets file |
| Container build | Passed with pinned Node/Python base-image digests after a transient Docker Hub routing failure |
| Other supported markets | BTC/USDC and ETH/USDC each returned 96 actual closed candles; transient DNS errors correctly returned 503 |
| Production container smoke | Passed: non-root, read-only filesystem, readiness, frontend/docs, owner bootstrap, secure cookies, closed signup and empty workspace; temporary container removed |
| Target-host HTTPS | Public host, DNS and TLS remain unverified |

Machine-readable local evidence (ignored by Git): `data/real-market-acceptance.json`, `data/qa-agent-builder/report.json`, `data/qa-navigation/report.json`, `data/container-smoke.json`, `data/qa-copilot/report.json`. Browser screenshots are in those QA folders. Unit fixtures use an isolated transport under `tests/`; actual production requests cannot select synthetic datasets.

Limits: fills are paper accounting using closed exchange candles. There is no live exchange execution, streaming forward paper engine, order-book liquidity model. Copilot reference mode, draft application and navigation are browser-tested; Gemini Flash-Lite help, navigation and draft extraction have also been exercised against the real API; hostile/invalid outputs and reserve-key behavior are covered by unit tests. Tests are not evidence of expected profit, and rejection thresholds cannot guarantee a maximum loss. Complete the target-host checklist in [DEPLOYMENT.md](../DEPLOYMENT.md) before inviting external users.

## Marketplace-first update

- `/` is public discovery for guests and authenticated users; `/explore` redirects there. Personal monitoring moved to `/overview`; publication and improvement are in `/developers`.
- Browser navigation: 15 distinct sections and 53 working internal links, no JavaScript or application API errors.
- Real publication flow: an agent tested on recorded exchange candles appeared on the homepage, then opened a private draft pinned to its source version. The temporary QA listing was removed.
- Marketplace browser regression covers guest/authenticated entry, responsive layout, filters and version handoff. Isolated browser-only fixtures test leaderboard eligibility, period/cost separation, tied ranks and return/drawdown sorting; these fixtures never enter the application database.
- Assistance regression covers public-only marketplace context and owner-only developer/workspace context. Handbook and Copilot now explain marketplace-first product roles and ranking methodology.
- The container checks above precede this UI update; the current local frontend build and backend are updated, but the previous Docker image was not rebuilt for this change.

Additional evidence: `data/qa-marketplace-first/report.json` and screenshots in the same folder.

## Gemini Copilot

- Server adapter: `gemini-3.1-flash-lite`, structured JSON response with local validation; provider-aware opt-in in chat and intent form.
- Real API: Russian explanation, allowlisted leaderboard navigation and ETH/USDC capital/risk extraction passed, with no strategy created. Evidence: `data/gemini-acceptance.json`.
- Browser: Gemini opt-in and actual Russian answer in the sidebar passed. Evidence: `data/qa-gemini/report.json` and `copilot.png`.
- Both configured keys were accepted by Google's model-discovery endpoint. The reserve is used for authentication failures, not quota or capacity errors; successful reserve selection is retained until restart.
- Initial 2.5 Flash requests were rejected for new users; 3.8 Flash returned capacity errors. Flash-Lite also returned a transient capacity error before successful acceptance. Provider availability remains external; errors leave drafts unchanged.
- Full regression: 175 Python tests, Ruff and frontend build passed. No billing settings changed. The existing Docker image predates this adapter update.
