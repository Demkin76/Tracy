import { chromium, expect } from "@playwright/test";
import fs from "node:fs/promises";

const base = "http://127.0.0.1:8000";
const out = new URL("../data/qa-agent-builder/", import.meta.url);
await fs.mkdir(out, { recursive: true });
const browser = await chromium.launch({
  headless: true,
  ...(process.env.TRACY_BROWSER_PATH
    ? { executablePath: process.env.TRACY_BROWSER_PATH }
    : {}),
});
const context = await browser.newContext({
  viewport: { width: 1440, height: 1100 },
});
const page = await context.newPage();
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
const report = { checks: [], started_at: new Date().toISOString() };
const check = (message) => {
  report.checks.push(message);
  console.log(message);
};
const count = async () =>
  (await (await context.request.get(base + "/v1/agents")).json()).items.length;
try {
  const signup = await context.request.post(base + "/v1/auth/signup", {
    data: {
      email: "builder-qa-" + Date.now() + "@tracy.local",
      name: "Onboarding QA",
      password: "local-builder-qa-password",
    },
  });
  expect(signup.status()).toBe(201);
  await page.goto(base + "/agents/new");
  await expect(
    page.getByRole("heading", { name: "What do you want this agent to do?" }),
  ).toBeVisible();
  await page.screenshot({
    path: new URL("describe.png", out).pathname,
    fullPage: true,
  });
  await page
    .getByLabel("Your intent", { exact: true })
    .fill(
      "Trade SOL/USDC with mean reversion, small positions and my approval for larger trades.",
    );
  await page.getByRole("button", { name: "Suggest guardrails" }).click();
  await page
    .getByLabel("Agent name", { exact: true })
    .fill("Reviewed browser agent");
  await expect(page.getByLabel("Allowed market")).toHaveValue("SOL/USDC");
  await expect(page.getByLabel("Strategy template")).toHaveValue(
    "mean_reversion",
  );
  expect(await count()).toBe(0);
  await page.screenshot({
    path: new URL("guardrails.png", out).pathname,
    fullPage: true,
  });
  await page.getByRole("button", { name: "Continue to test" }).click();
  await page.getByRole("button", { name: "Run backtests & checks" }).click();
  await expect(
    page.getByText("12/12 guardrail checks passed", { exact: true }),
  ).toBeVisible();
  expect(await count()).toBe(0);
  check("Describe, permissions and server tests create no agent");
  await page.reload();
  await expect(
    page.getByText("12/12 guardrail checks passed", { exact: true }),
  ).toBeVisible();
  check("Tested intent and results survive reload");
  await page.getByRole("button", { name: "Edit guardrails" }).click();
  await page
    .getByLabel("Approval required above (USDC)", { exact: true })
    .fill("50");
  await page.getByRole("button", { name: "Continue to test" }).click();
  await expect(
    page.getByRole("button", { name: "Review deployment" }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Run backtests & checks" }).click();
  await expect(
    page.getByText("12/12 guardrail checks passed", { exact: true }),
  ).toBeVisible();
  check("Editing a limit invalidates the test and requires a new run");
  await page.screenshot({
    path: new URL("tests.png", out).pathname,
    fullPage: true,
  });
  await page.getByRole("button", { name: "Review deployment" }).click();
  await expect(
    page.getByText("Required above 50 USDC", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Deploy paper agent" }),
  ).toBeDisabled();
  expect(await count()).toBe(0);
  await page.screenshot({
    path: new URL("review.png", out).pathname,
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 1,
    ),
  ).toBe(true);
  const consent = page.locator(".builder-confirm");
  expect(
    await consent
      .locator("input")
      .evaluate((el) => el.getBoundingClientRect().width),
  ).toBeLessThan(25);
  expect(
    await consent
      .locator("span")
      .evaluate((el) => el.getBoundingClientRect().width),
  ).toBeGreaterThan(150);
  await page.screenshot({
    path: new URL("review-mobile.png", out).pathname,
    fullPage: true,
  });
  await page
    .getByLabel(
      "I reviewed the intent, limits and test results. I authorize this paper deployment.",
    )
    .check();
  await page.getByRole("button", { name: "Deploy paper agent" }).click();
  await expect(page).toHaveURL(/\/strategies\/strategy_.*created=1/);
  await expect(
    page.getByRole("heading", { name: "Reviewed browser agent", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Created from a reviewed intent", { exact: true }),
  ).toBeVisible();
  expect(await count()).toBe(1);
  const sid = new URL(page.url()).pathname.split("/").at(-1);
  const detail = await (
    await context.request.get(base + "/v1/strategies/" + sid)
  ).json();
  expect(detail.guardrails.human_approval_above).toBe(50);
  expect(detail.performance.deployment.step).toBe(0);
  expect(detail.listed).toBe(false);
  check(
    "Explicit review creates one private paper agent with the exact tested limits",
  );
  await page
    .getByRole("link", { name: "View original intent & deployment review" })
    .click();
  await expect(
    page.getByText("12/12 guardrail checks passed", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Review deployment" }).click();
  await expect(
    page.getByRole("link", { name: "Open deployed agent" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Deploy paper agent" }),
  ).toHaveCount(0);
  expect(errors).toEqual([]);
  report.passed = true;
  check(
    "Original review remains accessible; mobile layout and browser errors checked",
  );
} catch (error) {
  report.passed = false;
  report.error = String(error);
  await page.screenshot({
    path: new URL("failure.png", out).pathname,
    fullPage: true,
  });
  throw error;
} finally {
  report.browser_errors = errors;
  await fs.writeFile(
    new URL("report.json", out),
    JSON.stringify(report, null, 2),
  );
  await browser.close();
}
