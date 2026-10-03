import { chromium, expect } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";
import crypto from "node:crypto";
const root = path.resolve(".."),
  output = path.join(root, "data", "qa-week1");
await fs.mkdir(output, { recursive: true });
const base = process.env.TRACY_URL || "http://127.0.0.1:8000";
const visible = process.argv.includes("--visible");
const live = process.argv.includes("--live");
const browser = await chromium.launch({
  channel: "chrome",
  headless: !visible,
});
const context = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
});
const page = await context.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
const report = {
  started_at: new Date().toISOString(),
  live,
  checks: [],
  actions: [],
};
const recipient = JSON.parse(
  await fs.readFile(
    path.join(root, "data/presentation-recipient.json"),
    "utf8",
  ),
).public_key;
const creds = visible
  ? JSON.parse(
      await fs.readFile(path.join(root, "data/tracy-owner.json"), "utf8"),
    )
  : {
      email: "qa-" + crypto.randomUUID() + "@example.test",
      password: crypto.randomBytes(24).toString("hex"),
      name: "QA workspace",
    };
const check = (label) => {
  report.checks.push(label);
  console.log(label);
};
try {
  await page.goto(base);
  await expect(
    page.getByRole("heading", { name: "Welcome back." }),
  ).toBeVisible();
  await page.screenshot({
    path: path.join(output, "01-login.png"),
    fullPage: true,
  });
  if (!visible) {
    await page
      .getByRole("button", { name: "New to Tracy? Create an account" })
      .click();
    await page.getByLabel("Your name", { exact: true }).fill(creds.name);
  }
  await page.getByLabel("Email", { exact: true }).fill(creds.email);
  await page.getByLabel("Password", { exact: true }).fill(creds.password);
  await page
    .getByRole("button", {
      name: visible ? "Sign in" : "Create account",
      exact: true,
    })
    .click();
  await expect(
    page.getByRole("link", { name: "My agents", exact: true }),
  ).toBeVisible();
  check("Account sign-in / signup");
  await page.getByRole("link", { name: "My agents", exact: true }).click();
  await page
    .getByRole("link", { name: "Create agent", exact: true })
    .first()
    .click();
  await page
    .getByLabel("Agent name", { exact: true })
    .fill("Tracy · payout assistant");
  await page
    .getByLabel("Description", { exact: true })
    .fill("Week-one demo: signed payouts with a daily budget.");
  await page.getByLabel("Allowed recipients", { exact: true }).fill(recipient);
  await page.getByLabel("Daily budget (SOL)", { exact: true }).fill("0.02");
  const registration = page.waitForResponse(
    (r) => r.url() === base + "/v1/agents" && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Create agent", exact: true }).click();
  const registered = await registration;
  expect(registered.status()).toBe(201);
  report.agent_id = (await registered.json()).agent_id;
  await expect(
    page.getByRole("button", { name: "Stop agent", exact: true }),
  ).toBeVisible();
  check("Create named agent with browser signing key");
  await page
    .getByLabel("Description", { exact: true })
    .fill("Policies, daily limits and verifiable Devnet actions.");
  await page.getByRole("button", { name: "Save details", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText("Agent details saved.");
  await page.getByLabel("Daily budget (SOL)", { exact: true }).fill("0.015");
  await page
    .getByRole("button", { name: "Save new policy version", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Policy v2", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".versions summary")).toHaveCount(2);
  check("Edit identity and append a policy version");
  await page.screenshot({
    path: path.join(output, "02-agent-settings.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "Stop agent", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Resume agent", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("link", { name: "Run signed action", exact: true })
    .click();
  async function send(amount, reason) {
    await page.getByLabel("Amount (SOL)", { exact: true }).fill(amount);
    const waiting = page.waitForResponse(
      (r) =>
        r.url() === base + "/v1/actions" && r.request().method() === "POST",
      { timeout: 180000 },
    );
    await page
      .getByRole("button", { name: "Sign & execute action", exact: true })
      .click();
    const res = await waiting;
    expect([201, 202]).toContain(res.status());
    let action = await res.json();
    report.actions.push(action);
    await fs.writeFile(
      path.join(output, "report.json"),
      JSON.stringify(report, null, 2),
    );
    for (let i = 0; action.status === "PENDING" && i < 8; i++) {
      const me = await (await context.request.get(base + "/v1/auth/me")).json();
      action = await (
        await context.request.post(
          base + "/v1/actions/" + action.action_id + "/reconcile",
          { headers: { "X-CSRF-Token": me.csrf_token } },
        )
      ).json();
      report.actions[report.actions.length - 1] = action;
      if (action.status === "PENDING")
        await new Promise((r) => setTimeout(r, 2000));
    }
    expect(action.reason).toBe(reason);
    if (action.receipt_id) {
      const proof = await (
        await context.request.get(
          base + "/v1/receipts/" + action.receipt_id + "/verify",
        )
      ).json();
      expect(proof.valid).toBe(true);
      report.actions[report.actions.length - 1].qa_verification = proof;
    }
    return action;
  }
  await send("0.01", "agent_stopped");
  check("Stopped agent rejects signed request and produces a valid receipt");
  await page.getByRole("link", { name: "Manage policy & status" }).click();
  await page.getByRole("button", { name: "Resume agent", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Stop agent", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("link", { name: "Run signed action", exact: true })
    .click();
  if (live) {
    await send("0.01", "exact_transfer_confirmed");
    check("Real Devnet payout and fresh on-chain verification");
    await send("0.01", "daily_budget_exceeded");
    check("Daily budget rejects a second payout");
  } else {
    await send("1", "amount_exceeds_limit");
    check("Transfer limit blocks execution");
  }
  await page
    .getByRole("link", { name: "Inspect proof receipt", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Verify receipt", exact: true })
    .click();
  await expect(page.locator(".verification-success")).toBeVisible({
    timeout: 30000,
  });
  await page.screenshot({
    path: path.join(output, "03-verified-rejection.png"),
    fullPage: true,
  });
  check("Receipt verification UI");
  await page.getByRole("link", { name: "Connect SDK", exact: true }).click();
  await page.getByLabel("Key name", { exact: true }).fill("Temporary QA key");
  await page
    .getByRole("button", { name: "Create API key", exact: true })
    .click();
  const issued = page.locator(".issued-key input");
  await expect(issued).toBeVisible();
  const raw = await issued.inputValue();
  const own = await context.request.get(base + "/v1/agents", {
    headers: { Authorization: "Bearer " + raw },
  });
  expect(own.status()).toBe(200);
  await page
    .getByRole("button", { name: "Revoke", exact: true })
    .last()
    .click();
  await expect(issued).toHaveCount(0);
  expect(
    (
      await context.request.get(base + "/v1/agents", {
        headers: { Authorization: "Bearer " + raw },
      })
    ).status(),
  ).toBe(401);
  check("Issue and revoke personal API key");
  await page.getByRole("link", { name: "My agents", exact: true }).click();
  await page.screenshot({
    path: path.join(output, "04-agents-desktop.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: path.join(output, "05-agents-mobile.png"),
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  check("Mobile layout fits the viewport");
  await page.setViewportSize({ width: 1440, height: 1000 });
  if (!visible) {
    await page.reload();
    await expect(
      page.getByRole("link", { name: "My agents", exact: true }),
    ).toBeVisible();
    await page
      .getByRole("link", { name: "Run an action", exact: true })
      .click();
    await expect(
      page.getByRole("heading", {
        name: "Create a browser demo agent",
        exact: true,
      }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Sign out", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "Welcome back.", exact: true }),
    ).toBeVisible();
    check("Persistent login; ephemeral signing key; explicit logout");
  }
  expect(errors).toEqual([]);
  report.ready = true;
  report.browser_errors = errors;
  check("No browser JavaScript errors");
} catch (e) {
  report.error = String(e);
  await page.screenshot({
    path: path.join(output, "failure.png"),
    fullPage: true,
  });
  console.error(e);
  process.exitCode = 1;
}
await fs.writeFile(
  path.join(output, visible ? "demo-ready.json" : "report.json"),
  JSON.stringify(report, null, 2),
);
if (visible && report.ready) {
  console.log("Tracy demo ready; close its browser to end this helper.");
  await new Promise((r) => browser.on("disconnected", r));
} else await browser.close();
