import { chromium, expect } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";
import crypto from "node:crypto";
const root = path.resolve(".."),
  out = path.join(root, "data", "qa-platform"),
  base = "http://127.0.0.1:8000";
await fs.mkdir(out, { recursive: true });
const browser = await chromium.launch({ channel: "chrome", headless: true });
const context = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
});
const guest = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
});
const page = await context.newPage(),
  publicPage = await guest.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
publicPage.on("pageerror", (e) => errors.push(e.message));
const report = { checks: [], started_at: new Date().toISOString() };
const check = (t) => {
  report.checks.push(t);
  console.log(t);
};
const email = "platform-" + crypto.randomUUID() + "@example.test",
  password = crypto.randomBytes(24).toString("hex");
const name = "Platform QA " + crypto.randomUUID().slice(0, 6);
const recipient = JSON.parse(
  await fs.readFile(
    path.join(root, "data/presentation-recipient.json"),
    "utf8",
  ),
).public_key;
try {
  await publicPage.goto(base + "/explore");
  await expect(
    publicPage.getByRole("heading", {
      name: "Meet agents. Inspect their actions.",
    }),
  ).toBeVisible();
  await page.goto(base);
  await page
    .getByRole("button", { name: "New to Tracy? Create an account" })
    .click();
  await page.getByLabel("Your name", { exact: true }).fill("Platform QA");
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();
  await page.getByRole("link", { name: "My agents", exact: true }).click();
  await page
    .getByRole("link", { name: "Create agent", exact: true })
    .first()
    .click();
  await page.getByLabel("Agent name", { exact: true }).fill(name);
  await page.getByLabel("Allowed recipients", { exact: true }).fill(recipient);
  const register = page.waitForResponse(
    (r) => r.url() === base + "/v1/agents" && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Create agent", exact: true }).click();
  report.agent_id = (await (await register).json()).agent_id;
  await expect(
    page.getByRole("heading", { name: "Public profile", exact: true }),
  ).toBeVisible();
  expect(
    (
      await (
        await guest.request.get(base + "/v1/public/agents/" + report.agent_id)
      ).json()
    ).detail,
  ).toBe("Public agent not found");
  await page
    .getByLabel("Short public introduction", { exact: true })
    .fill("Public evidence with explicit consent.");
  await page
    .getByRole("checkbox", {
      name: "Publish this profile and all past and future receipts",
      exact: false,
    })
    .check();
  await page
    .getByRole("button", { name: "Publish agent", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Unpublish agent", exact: true }),
  ).toBeVisible();
  check("Private by default; explicit profile and history publication");
  await page
    .getByRole("link", { name: "Run signed action", exact: true })
    .click();
  await page.getByLabel("Amount (SOL)", { exact: true }).fill("1");
  const result = page.waitForResponse(
    (r) => r.url() === base + "/v1/actions" && r.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Sign & execute action", exact: true })
    .click();
  const action = await (await result).json();
  expect(action.status).toBe("REJECTED");
  report.receipt_id = action.receipt_id;
  await page
    .getByRole("link", { name: "Inspect proof receipt", exact: true })
    .click();
  await page
    .getByRole("checkbox", {
      name: "I want to share this full receipt",
      exact: false,
    })
    .check();
  await page
    .getByRole("button", { name: "Create proof link", exact: true })
    .click();
  const shareLink = page.locator(".share-panel .notice a");
  await expect(shareLink).toBeVisible();
  report.shared_url = await shareLink.getAttribute("href");
  await publicPage.goto(report.shared_url);
  await expect(
    publicPage.getByRole("heading", {
      name: "A record you can verify.",
      exact: true,
    }),
  ).toBeVisible();
  await publicPage
    .getByRole("button", { name: "Verify public proof", exact: true })
    .click();
  await expect(publicPage.locator(".verification-success")).toContainText(
    "Valid signed refusal",
  );
  check("Anonymous scoped proof link with browser and gateway verification");
  await page.getByRole("link", { name: "Explore agents", exact: true }).click();
  await page.getByLabel("Search public agents", { exact: true }).fill(name);
  await expect(page.locator(".public-agent-card")).toHaveCount(1);
  await page.getByRole("button", { name: "Compare", exact: true }).click();
  await page
    .getByRole("link", { name: "Compare evidence", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Evidence, side by side.", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("cell", { name: "Insufficient history", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: path.join(out, "compare.png"),
    fullPage: true,
  });
  check("Catalog search and honest small-sample comparison");
  await page.getByRole("link", { name: name + " \u2197", exact: true }).click();
  await page.getByRole("button", { name: "Save agent", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Saved to watchlist", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: path.join(out, "public-profile.png"),
    fullPage: true,
  });
  await page.getByRole("link", { name: "My workspace", exact: false }).click();
  await page.getByRole("link", { name: "Run an action", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Sign & execute action", exact: true }),
  ).toBeVisible();
  check("Public navigation preserves browser agent signing session");
  await page.getByRole("link", { name: "Watchlist", exact: true }).click();
  await expect(page.locator(".public-agent-card")).toHaveCount(1);
  await page.getByRole("link", { name: "Activity", exact: true }).click();
  await page.getByLabel("Status", { exact: true }).selectOption("REJECTED");
  await expect(page.locator("tbody tr")).toHaveCount(1);
  const dl = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export CSV", exact: true }).click();
  const download = await dl;
  await download.saveAs(path.join(out, "history.csv"));
  expect(await fs.readFile(path.join(out, "history.csv"), "utf8")).toContain(
    action.action_id,
  );
  await page.screenshot({
    path: path.join(out, "activity.png"),
    fullPage: true,
  });
  await page.getByRole("link", { name: "Analytics", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Daily activity", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: path.join(out, "analytics.png"),
    fullPage: true,
  });
  check("Owner watchlist, filtered history, CSV and analytics");
  await page.getByRole("link", { name: "Notifications", exact: true }).click();
  await expect(
    page.getByText("1 unread updates", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Mark all as read", exact: true })
    .click();
  await expect(
    page.getByText("0 unread updates", { exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Devnet funding", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Execution wallet", exact: true }),
  ).toBeVisible();
  check("Notifications and Devnet funding view");
  await page
    .getByRole("link", { name: "Account & security", exact: true })
    .click();
  await page.getByRole("button", { name: "Revoke link", exact: true }).click();
  await publicPage.reload();
  await expect(publicPage.getByRole("alert")).toContainText(
    "expired, revoked or not found",
  );
  await page
    .getByLabel("Password to issue recovery code", { exact: true })
    .fill(password);
  await page
    .getByRole("button", { name: "Generate recovery code", exact: true })
    .click();
  const code = await page
    .getByLabel("Save this recovery code", { exact: true })
    .inputValue();
  expect(code.startsWith("tracy_recovery_")).toBe(true);
  await page.getByRole("link", { name: "My agents", exact: true }).click();
  await page
    .getByRole("link", { name: "Manage agent", exact: false })
    .first()
    .click();
  await page
    .getByRole("button", { name: "Unpublish agent", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Publish agent", exact: true }),
  ).toBeVisible();
  expect(
    (
      await guest.request.get(base + "/v1/public/agents/" + report.agent_id)
    ).status(),
  ).toBe(404);
  check("Revocation of links and directory access");
  await publicPage.goto(base + "/recover");
  await publicPage.getByLabel("Email", { exact: true }).fill(email);
  await publicPage.getByLabel("Recovery code", { exact: true }).fill(code);
  await publicPage
    .getByLabel("New password", { exact: true })
    .fill("recovered-" + password);
  await publicPage
    .getByRole("button", { name: "Reset password", exact: true })
    .click();
  await expect(publicPage.locator(".verification-success")).toContainText(
    "Password reset",
  );
  expect((await context.request.get(base + "/v1/auth/me")).status()).toBe(401);
  check("One-time recovery invalidates previous sessions");
  await publicPage.goto(base + "/explore");
  await publicPage.setViewportSize({ width: 390, height: 844 });
  await publicPage.screenshot({
    path: path.join(out, "explore-mobile.png"),
    fullPage: true,
  });
  expect(
    await publicPage.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await publicPage.setViewportSize({ width: 1440, height: 1000 });
  await publicPage.screenshot({
    path: path.join(out, "explore-desktop.png"),
    fullPage: true,
  });
  expect(errors).toEqual([]);
  check("Mobile layout and no browser JavaScript errors");
  report.passed = true;
} catch (e) {
  report.error = String(e);
  report.browser_errors = errors;
  console.error(e);
  await page.screenshot({
    path: path.join(out, "failure.png"),
    fullPage: true,
  });
  process.exitCode = 1;
}
await fs.writeFile(
  path.join(out, "report.json"),
  JSON.stringify(report, null, 2),
);
await browser.close();
