import { HelpLink } from "./Copilot";
import { useEffect, useState } from "react";
import { api } from "./api";
import { getWallets } from "@wallet-standard/app";
import type { WalletAccount } from "@wallet-standard/base";
type Wallet = {
  account: WalletAccount;
  sign: (
    ...inputs: {
      account: WalletAccount;
      chain: "solana:devnet";
      transaction: Uint8Array;
    }[]
  ) => Promise<{ signedTransaction: Uint8Array }[]>;
};
export async function connectWallet() {
  const provider = getWallets()
    .get()
    .find(
      (w) =>
        "standard:connect" in w.features &&
        "solana:signTransaction" in w.features,
    );
  if (!provider)
    throw new Error(
      "Open a Wallet Standard compatible Solana wallet extension with a separate Devnet test wallet.",
    );
  const connect = provider.features["standard:connect"] as {
    connect: () => Promise<{ accounts: readonly WalletAccount[] }>;
  };
  const { accounts } = await connect.connect();
  const account = accounts.find((a) => a.chains.includes("solana:devnet"));
  if (!account)
    throw new Error("Select a wallet account with Solana Devnet support.");
  const feature = provider.features["solana:signTransaction"] as {
    signTransaction: Wallet["sign"];
  };
  return {
    wallet: { account, sign: feature.signTransaction },
    payer: account.address,
  };
}
export async function signDevnet(raw: string, wallet: Wallet) {
  const [signed] = await wallet.sign({
    account: wallet.account,
    chain: "solana:devnet",
    transaction: Uint8Array.from(atob(raw), (c) => c.charCodeAt(0)),
  });
  return btoa(String.fromCharCode(...signed.signedTransaction));
}
type Invoice = {
  invoice: {
    body: {
      invoice_id: string;
      creator_lamports: number;
      platform_lamports: number;
      expires_at: number;
      creator_wallet: string;
      platform_wallet: string;
    };
  };
  receipt: unknown;
};
export function BundlePayments({
  id,
  owner = false,
}: {
  id: string;
  owner?: boolean;
}) {
  const [price, setPrice] = useState<{ lamports: number } | null>(null),
    [amount, setAmount] = useState(100000),
    [recipient, setRecipient] = useState(""),
    [invoice, setInvoice] = useState<Invoice | null>(null),
    [signature, setSignature] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  useEffect(() => {
    api<{ lamports: number }>(`/public/bundles/${id}/price`)
      .then(setPrice)
      .catch(() => setPrice(null));
  }, [id]);
  const work = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="panel editor">
      <h2>Test-SOL license</h2>
      <p>
        Solana Devnet only. 95% to the creator, 5% to Tracy, plus the network
        fee. Public strategy evidence remains readable.
      </p>
      {error && <p role="alert">{error}</p>}
      {price && (
        <p>
          {price.lamports
            ? `${price.lamports / 1e9} test SOL`
            : "Free to clone"}
        </p>
      )}
      {owner && (
        <details>
          <summary>Set a test price</summary>
          <label>
            Price in lamports (max 1,000,000)
            <input
              type="number"
              value={amount}
              onChange={(e) => setAmount(Number(e.target.value))}
            />
          </label>
          <label>
            Creator Devnet wallet
            <input
              value={recipient}
              onChange={(e) => setRecipient(e.target.value)}
            />
          </label>
          <button
            disabled={busy}
            onClick={() =>
              void work(async () => {
                setPrice(
                  await api(`/adaptive/bundles/${id}/price`, {
                    method: "PUT",
                    body: JSON.stringify({
                      lamports: amount,
                      creator_wallet: recipient,
                    }),
                  }),
                );
              })
            }
          >
            Save test price and payout wallet
          </button>
        </details>
      )}
      {!!price?.lamports && !invoice && (
        <button
          disabled={busy}
          onClick={() =>
            void work(async () => {
              const { payer } = await connectWallet();
              setInvoice(
                await api(`/adaptive/bundles/${id}/checkout`, {
                  method: "POST",
                  body: JSON.stringify({ payer }),
                }),
              );
            })
          }
        >
          Connect Devnet wallet and review checkout
        </button>
      )}
      {invoice && (
        <>
          <button
            className="secondary"
            disabled={busy}
            onClick={() => {
              setInvoice(null);
              setSignature("");
            }}
          >
            Start a new checkout
          </button>
          <p>
            Creator: {invoice.invoice.body.creator_lamports} lamports →{" "}
            <code>{invoice.invoice.body.creator_wallet}</code>
          </p>
          <p>
            Tracy: {invoice.invoice.body.platform_lamports} lamports →{" "}
            <code>{invoice.invoice.body.platform_wallet}</code>
          </p>
          <p>
            Invoice expires{" "}
            {new Date(
              invoice.invoice.body.expires_at * 1000,
            ).toLocaleTimeString()}
          </p>
          {invoice.receipt ? (
            <p>Finalized payment verified. You can create your own instance.</p>
          ) : (
            <>
              <button
                disabled={busy || !!signature}
                onClick={() =>
                  void work(async () => {
                    const { wallet } = await connectWallet();
                    const p = await api<{ transaction: string }>(
                      `/adaptive/invoices/${invoice.invoice.body.invoice_id}/prepare`,
                      { method: "POST" },
                    );
                    const transaction = await signDevnet(p.transaction, wallet);
                    const sent = await api<{ signature: string }>(
                      `/adaptive/invoices/${invoice.invoice.body.invoice_id}/submit`,
                      { method: "POST", body: JSON.stringify({ transaction }) },
                    );
                    setSignature(sent.signature);
                  })
                }
              >
                Sign and pay with test SOL
              </button>
              <label>
                Transaction signature
                <input
                  value={signature}
                  onChange={(e) => setSignature(e.target.value)}
                />
              </label>
              <button
                disabled={busy || !signature}
                onClick={() =>
                  void work(async () => {
                    setInvoice(
                      await api(
                        `/adaptive/invoices/${invoice.invoice.body.invoice_id}/confirm`,
                        { method: "POST", body: JSON.stringify({ signature }) },
                      ),
                    );
                  })
                }
              >
                Verify finalized payment
              </button>
            </>
          )}
        </>
      )}
    </section>
  );
}

type Swap = {
  quote: {
    body: {
      swap_id: string;
      transaction: string;
      amount_raw: number;
      quoted_output_raw: number;
      minimum_output_raw: number;
      input_mint: string;
      output_mint: string;
      note: string;
    };
  };
  receipt: { body: { signature: string; output_raw: number } } | null;
};
export function DevnetDexPage() {
  const [info, setInfo] = useState<{
      enabled: boolean;
      pool: string;
      test_token: string;
    } | null>(null),
    [side, setSide] = useState("BUY"),
    [amount, setAmount] = useState(100000),
    [swap, setSwap] = useState<Swap | null>(null),
    [signature, setSignature] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    api<typeof info>("/adaptive/dex")
      .then(setInfo)
      .catch((e) => setError(String(e)));
  }, []);
  const work = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="adaptive-page">
      <header>
        <div className="eyebrow">SOLANA DEVNET / REAL TRANSACTIONS</div>
        <h1>Test DEX execution</h1>
        <HelpLink topic="devnet-dex" />
        <p>
          Exchange wrapped test SOL and a Devnet test token through Raydium
          CPMM. These prices and fills are separate from paper performance and
          APR training.
        </p>
      </header>
      {error && <p role="alert">{error}</p>}
      {info && (
        <section className="panel editor">
          <p>
            {info.enabled
              ? "Devnet adapter enabled"
              : "Devnet adapter disabled on this deployment"}
          </p>
          <p>
            Pool:{" "}
            <a
              href={`https://explorer.solana.com/address/${info.pool}?cluster=devnet`}
              target="_blank"
              rel="noreferrer"
            >
              {info.pool}
            </a>
          </p>
          <p>
            Test token mint: <code>{info.test_token}</code>. Its symbol does not
            guarantee a peg or value.
          </p>
          <p>
            Maximum size: 0.001 test SOL equivalent. Wallet must have extra test
            SOL for account rent and transaction fees.
          </p>
          <label>
            Side
            <select
              value={side}
              onChange={(e) => {
                setSide(e.target.value);
                setSwap(null);
              }}
            >
              <option value="BUY">Test SOL → test token</option>
              <option value="SELL">Test token → wrapped test SOL</option>
            </select>
          </label>
          <label>
            Input in raw token units
            <input
              type="number"
              min="1"
              value={amount}
              onChange={(e) => {
                setAmount(Number(e.target.value));
                setSwap(null);
              }}
            />
          </label>
          <button
            disabled={busy || !info.enabled}
            onClick={() =>
              void work(async () => {
                const { payer } = await connectWallet();
                setSwap(
                  await api("/adaptive/dex/quotes", {
                    method: "POST",
                    body: JSON.stringify({
                      payer,
                      side,
                      amount_raw: amount,
                      slippage_bps: 50,
                    }),
                  }),
                );
                setSignature("");
              })
            }
          >
            Connect wallet and obtain quote
          </button>
        </section>
      )}
      {swap && (
        <section className="panel editor">
          <h2>Review Devnet swap</h2>
          <p>
            Input: {swap.quote.body.amount_raw} raw · output quote:{" "}
            {swap.quote.body.quoted_output_raw} raw · minimum:{" "}
            {swap.quote.body.minimum_output_raw} raw
          </p>
          <p>{swap.quote.body.note}</p>
          {swap.receipt ? (
            <p>
              Finalized: received {swap.receipt.body.output_raw} raw.{" "}
              <a
                href={`https://explorer.solana.com/tx/${swap.receipt.body.signature}?cluster=devnet`}
                target="_blank"
                rel="noreferrer"
              >
                Inspect network evidence
              </a>
            </p>
          ) : (
            <>
              <button
                disabled={busy || !!signature}
                onClick={() =>
                  void work(async () => {
                    const { wallet } = await connectWallet();
                    const transaction = await signDevnet(
                      swap.quote.body.transaction,
                      wallet,
                    );
                    const r = await api<{ signature: string }>(
                      `/adaptive/dex/${swap.quote.body.swap_id}/submit`,
                      { method: "POST", body: JSON.stringify({ transaction }) },
                    );
                    setSignature(r.signature);
                  })
                }
              >
                Sign and submit test swap
              </button>
              <label>
                Transaction signature
                <input
                  value={signature}
                  onChange={(e) => setSignature(e.target.value)}
                />
              </label>
              <button
                disabled={busy || !signature}
                onClick={() =>
                  void work(async () => {
                    setSwap(
                      await api(
                        `/adaptive/dex/${swap.quote.body.swap_id}/confirm`,
                        { method: "POST", body: JSON.stringify({ signature }) },
                      ),
                    );
                  })
                }
              >
                Verify finalized swap
              </button>
            </>
          )}
        </section>
      )}
    </div>
  );
}
