import { chromium, expect } from "@playwright/test";
import fs from "node:fs/promises";
const base = "http://127.0.0.1:8001";
const browser = await chromium.launch({
  headless: true,
  ...(process.env.TRACY_BROWSER_PATH
    ? { executablePath: process.env.TRACY_BROWSER_PATH }
    : {}),
});
const context = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
});
const page = await context.newPage();
const failures = [];
page.on("pageerror", (e) => failures.push(e.message));
try {
  const creds = JSON.parse(
    await fs.readFile(
      new URL("../data/tracy-owner.json", import.meta.url),
      "utf8",
    ),
  );
  const login = await context.request.post(base + "/v1/auth/login", {
    data: { email: creds.email, password: creds.password },
  });
  expect(login.ok()).toBe(true);
  await page.goto(base + "/lab");
  await page
    .getByLabel("Name", { exact: true })
    .fill("BTC Momentum · Devnet acceptance");
  await page.getByRole("checkbox", { name: /I reviewed these rules/ }).check();
  await page
    .getByRole("button", { name: "Create learning instance", exact: true })
    .click();
  await page.waitForURL(/\/lab\/adaptive_/);
  const agentUrl = page.url();
  const training = page.waitForResponse(
    (r) => r.url().endsWith("/experiments") && r.request().method() === "POST",
    { timeout: 90000 },
  );
  await page
    .getByRole("button", { name: "Run historical experiment", exact: true })
    .click();
  const response = await training;
  const report = await response.json();
  expect(response.ok(), JSON.stringify(report.detail)).toBe(true);
  await expect(
    page.getByText("Original baseline", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Freeze this revision", exact: true })
    .click();
  await page.waitForURL(/\/lab\/bundles\/bundle_/);
  const bundleUrl = page.url();
  await page
    .getByRole("checkbox", { name: "I reviewed the public disclosure." })
    .check();
  await page
    .getByRole("button", { name: "Publish to Bundle marketplace", exact: true })
    .click();
  await expect(
    page.getByRole("link", { name: "View public listing →" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "View public listing →" }).click();
  await page.waitForURL(/\/bundles\/bundle_/);
  await expect(
    page.getByText("Strategy + agent + learned state", { exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "../data/adaptive-bundle-desktop.png",
    fullPage: true,
  });
  await page
    .getByRole("button", {
      name: "Create instance with learned state",
      exact: true,
    })
    .click();
  await page.waitForURL(/\/lab\/adaptive_/);
  await expect(page.getByText(/Personal closed trades: 0/)).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: "../data/adaptive-agent-mobile.png",
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth + 1,
    ),
  ).toBe(true);
  expect(failures).toEqual([]);
  await fs.writeFile(
    "../data/adaptive-acceptance.json",
    JSON.stringify(
      { agentUrl, bundleUrl, cloneUrl: page.url(), report },
      null,
      2,
    ),
  );
  console.log(
    JSON.stringify(
      {
        agentUrl,
        bundleUrl,
        gate: report.body.gate,
        baseline: report.body.baseline.metrics.pnl,
        candidate: report.body.candidate.metrics.pnl,
        pageErrors: failures,
      },
      null,
      2,
    ),
  );
} finally {
  await browser.close();
}
