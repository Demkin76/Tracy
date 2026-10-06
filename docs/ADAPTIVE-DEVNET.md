# Adaptive Tracy: devnet acceptance

This implementation is a test environment with **virtual trading capital** and
optional **real Solana Devnet memo transactions**. It does not send exchange
orders, trade Devnet DEX tokens, or support mainnet execution. No deposit is needed.

## Run locally

From the repository root, with the existing `.env` and dependencies installed:

```bash
cd frontend
npm run build
cd ..
.venv/bin/python scripts/run_adaptive_devnet.py
```

Open `http://127.0.0.1:8001/lab`. This uses a separate database,
`data/tracy-adaptive-devnet.sqlite3`, and the local owner credentials already in
`data/tracy-owner.json`. The launcher does not print credentials. It keeps legacy
Solana transfer execution disabled and enables only the new memo feature. It
reuses the configured signing and test-wallet identities; preserve `.env` with
the database. Never commit either. Production on Daytona is a separate deployment.

The local machine and server process must remain running for a 24-hour experiment.
The worker resumes persisted runs after a process restart. Missing candles or a
delay greater than two minutes after a candle close prevent historical catch-up:
the comparison closes at a current quote and records the interruption. This is
not a claim of uninterrupted 24/7 availability on a laptop.

## User path

1. Adaptive Lab: select momentum, mean reversion or SMA crossover. Review virtual
   capital, costs, fixed risk limits and the allowed learning variants.
2. Alternatively, import the supplied Pine Script v6 SMA example. It is a strict
   long-only subset; extra statements and other Pine constructs are rejected.
   Or create a strategy using the existing Gemini-assisted builder, then select
   **Learn from this strategy** on the strategy detail page.
3. Create the learning instance. Strategy APR is fixed; agent APR starts with
   independent outcome counts. No trades are copied from other agents.
4. Run a historical experiment. Defaults are 576 completed training candles and
   288 subsequent validation candles. Binance is the real price source, with a
   stored snapshot and provenance. Data failure aborts; no generated prices.
5. Inspect baseline, incumbent and learned candidate on the same validation
   period. Read the gate checks and signed JSON report. Activate only after an
   explicit review; failed gates cannot activate.
6. Start the 24-hour forward comparison. Both policies start with independent
   virtual capital. They observe new quotes, while the active policy stays frozen.
   New agent outcomes accumulate learning counts for a later reviewed experiment.
7. Freeze a Bundle. Publication is separate and explicitly discloses strategy
   source, risk settings, learned counts and experiment evidence.
8. Record/verify its Solana Devnet memo. Pending is not confirmed. The feature
   requires `POA_ADAPTIVE_DEVNET_ANCHORS_ENABLED=true`, accessible Devnet RPC and
   a small balance of **test SOL**. Only the bundle hash is written on-chain.
9. A visitor can create a rules-only instance or inherit learning. Both receive
   separate capital and zero personal trade history. Inherited learning retains
   its data cutoff, preventing reuse of already observed data as fresh training.

## What APR means here

`tracy.strategy-apr/1` is a signed immutable document containing normalized rules,
execution assumptions, risk settings and the authorized learning boundary.
It is an implementation schema, not a claim of compatibility with an external APR
standard. Strategy source and configuration remain fixed across learned copies.

`tracy.agent-apr/1` stores three arms, Beta prior/counts, net realized PnL per arm,
active arm, observed-data cutoff and experiment lineage. Momentum/reversion arms
are the reviewed threshold, half and one-and-a-half times that threshold. SMA
arms require 0, 5 or 10 bps of separation at a crossover.

Training selects arms with a deterministic UCB rule. Only executed simulated
closed outcomes update counts, after costs: positive increments alpha; zero or
negative increments beta. Counts start with Beta(1,1). They describe outcomes,
**not calibrated probabilities of future profit**. The explanation is derived
from these recorded counts and gate checks, not fabricated LLM reasoning.

Candidate selection uses only training outcomes. The validation interval freezes
all policies. Its outcomes do not update learning counts. An observed-data cutoff
includes validation, so later training cannot silently reuse the same interval.

Activation requires all of:

- At least three training exits for the selected candidate arm.
- At least five validation exits each for baseline, incumbent and candidate.
- Candidate return beats both comparators by more than 0.05 percentage points.
- Candidate max drawdown is no worse than either comparator and below the limit.
- Owner review of the exact report hash and current agent revision.

An improvement can mean **less loss**, not positive profit. Passing one interval
does not establish out-of-sample profitability across market regimes. There is
no autonomous rewrite of risk limits, program code, capital or trading permissions.

## Execution and risk semantics

Historical signals use prior closes, then simulate next-bar-open fills with
configured fees/slippage. Final liquidation is a disclosed testing convention.
SMA imports preserve crossover entry/crossunder exit; they have no timed exit.
The Pine importer is not a full TradingView compiler or broker emulator.

Forward uses public Binance REST bid/ask and top-of-book size, with local receipt
timestamps. It rejects invalid, wide-spread (>50 bps), slow (>5 seconds) or
insufficient-size quotes. It simulates marketable orders with adverse slippage
and fees; it does not model order-book queues, partial fills or exchange matching.
Decisions occur on new completed candles, not every market tick. It does not
replay missed decisions at old prices after downtime.

Risk limits gate entries. Risk-triggered and end-of-run exits can reduce existing
inventory above entry notional limits without creating a short. Daily loss and
drawdown trigger exits at the next available observation, **not guaranteed stop
prices**. Gaps, observation cadence and unavailable quotes can exceed the limit.
Manual Stop moves to STOPPING until a fresh quote permits closing both portfolios;
the UI must not report zero exposure just because Stop was clicked.

Each forward observation is tied to a signed hash chain and full portfolio state.
Concurrent refreshes use optimistic state checks. Repeated experiment request IDs
are idempotent, and stale agent revisions cannot overwrite newer state.

## Bundles and evidence

`tracy.bundle/1` freezes engine version, original APR, learned APR, signed report
and completed forward evidence. Personal activity starts empty when cloned;
inherited experience is labeled separately. Bundles are free preview listings:
there is no payment, license enforcement, custody or revenue distribution system.

A memo commits `tracy-bundle:<sha256>` using a configured Devnet wallet. Before
signing, both submission and verification endpoints must return Solana Devnet's
genesis hash. Raw signed transactions are persisted before broadcast; a retry
reuses the same transaction. Verification checks the read-back signature, exact
memo, signer, instruction count and absence of execution errors. An on-chain memo
proves a recorded hash, not profitability, data independence or exchange execution.

The operator controls the signing key. Verify exported reports against an
independently trusted public key. Source API provenance/hash is not an exchange
signature. No part of this experiment guarantees break-even.

## Verification commands

```bash
.venv/bin/python -m pytest -q
cd frontend
npm run build
node qa-adaptive.mjs
```

The browser acceptance uses actual Binance candles through the local server and
creates explicitly named local test records. Unit tests use fixtures to exercise
failure modes. Keep these two sources of evidence distinct.

Sources: [Pine strategies](https://www.tradingview.com/pine-script-docs/concepts/strategies/),
[Solana Memo](https://www.solana-program.com/docs/memo),
[Devnet identity check](https://solana.com/docs/rpc/http/getgenesishash).
