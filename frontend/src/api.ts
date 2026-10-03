import canonicalize from "canonicalize";

export type Agent = {
  managed: boolean;
  agent_id: string;
  name: string;
  public_key: string;
  listed: boolean;
  category: string;
  tagline: string;
  description: string;
  active: boolean;
  policy_version: number;
  budget: {
    day: string;
    used_lamports: number;
    limit_lamports: number;
    remaining_lamports: number;
  };
  policy: {
    max_transfer_sol: number;
    daily_budget_sol: number;
    allowed_recipients: string[];
    allowed_actions: string[];
  };
};
export type Action = {
  action_id: string;
  status: string;
  reason: string;
  created_at: number;
  receipt_id: string | null;
  tx_signature: string | null;
  request: { params: { amount: number; to: string } };
  receipt?: Receipt | null;
};
export type Receipt = {
  receipt_id: string;
  agent_id: string;
  agent_name: string;
  action: string;
  requested: { amount: number; to: string };
  status: string;
  reason: string;
  timestamp: number;
  sequence: number;
  execution_wallet: string;
  poa_public_key: string;
  previous_receipt_hash: string | null;
  receipt_hash: string;
  poa_signature: string;
  policy: {
    approved: boolean;
    version?: number;
    snapshot?: Agent["policy"];
    context?: Record<string, unknown>;
  };
  result: { status: string; tx_signature: string | null };
  verification: { status: string; slot: number | null };
};
export type Config = {
  network: string;
  execution_wallet: string;
  poa_public_key: string;
};
export type Checks = {
  valid: boolean;
  hash_valid: boolean;
  signature_valid: boolean;
  request_signature_valid: boolean;
  chain_valid: boolean;
  evidence_valid: boolean | null;
  evidence_status: string;
};
let csrfToken: string | null = null;
export const setCsrf = (value: string | null) => {
  csrfToken = value;
};
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}
export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path.startsWith("/v2/") ? path : "/v1" + path, {
    ...options,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {}),
      ...options?.headers,
    },
  });
  const body = await response.json();
  if (!response.ok)
    throw new ApiError(
      typeof body.detail === "string"
        ? body.detail
        : JSON.stringify(body.detail),
      response.status,
    );
  return body as T;
}
export const short = (value: string, n = 6) =>
  value.length > n * 2 + 3 ? value.slice(0, n) + "…" + value.slice(-n) : value;
export const base64 = (bytes: ArrayBuffer) =>
  btoa(String.fromCharCode(...new Uint8Array(bytes)));
const fromBase64 = (text: string) =>
  Uint8Array.from(atob(text), (c) => c.charCodeAt(0));
export async function signAction(
  key: CryptoKey,
  agentId: string,
  to: string,
  amount: number,
) {
  const payload = {
    request_id: "req_" + crypto.randomUUID().replaceAll("-", ""),
    agent_id: agentId,
    action: "solana.transfer",
    params: { to, amount },
    timestamp: Math.floor(Date.now() / 1000),
  };
  const signature = await crypto.subtle.sign(
    "Ed25519",
    key,
    new TextEncoder().encode(canonicalize(payload)!),
  );
  return { ...payload, signature: base64(signature) };
}
export async function verifyLocally(
  receipt: Receipt,
  trustedKey: string,
): Promise<boolean> {
  const { receipt_hash, poa_signature, ...payload } = receipt;
  const hash = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(canonicalize(payload)!),
  );
  const hex = [...new Uint8Array(hash)]
    .map((x) => x.toString(16).padStart(2, "0"))
    .join("");
  const key = await crypto.subtle.importKey(
    "raw",
    fromBase64(trustedKey),
    "Ed25519",
    false,
    ["verify"],
  );
  return (
    hex === receipt_hash &&
    receipt.poa_public_key === trustedKey &&
    (await crypto.subtle.verify(
      "Ed25519",
      key,
      fromBase64(poa_signature),
      hash,
    ))
  );
}
export function download(value: unknown, filename: string) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
