import { chromium, expect as baseExpect } from "@playwright/test";
import fs from "node:fs/promises";
const expect = baseExpect.configure({ timeout: 30000 });
const base = "http://127.0.0.1:8000";
const out = new URL("../data/qa-copilot/", import.meta.url);
await fs.mkdir(out, { recursive: true });
const browser = await chromium.launch({
  headless: true,
  ...(process.env.TRACY_BROWSER_PATH
    ? { executablePath: process.env.TRACY_BROWSER_PATH }
    : {}),
});
const context = await browser.newContext({
  viewport: { width: 1600, height: 1100 },
});
const page = await context.newPage();
const errors = [],
  checks = [];
page.on("pageerror", (e) => errors.push(e.message));
const report = { checks };
const check = (s) => {
  checks.push(s);
  console.log(s);
};
try {
  const signup = await context.request.post(base + "/v1/auth/signup", {
    data: {
      email: "copilot-qa-" + Date.now() + "@tracy.local",
      name: "Copilot QA",
      password: "local-copilot-qa-password",
    },
  });
  expect(signup.status()).toBe(201);
  await page.goto(base + "/agents/new");
  await page
    .getByLabel("Your intent", { exact: true })
    .fill(
      "Trade ETH/USDC with momentum, capital 2000 USDC, max position 200 USDC, max trade 100 USDC, daily loss 50 USDC, approval above 80 USDC.",
    );
  await page.getByRole("button", { name: "Suggest guardrails" }).click();
  await expect(
    page.getByLabel("Paper capital (USDC)", { exact: true }),
  ).toHaveValue("2000");
  await expect(
    page.getByLabel("Max position (USDC)", { exact: true }),
  ).toHaveValue("200");
  await expect(
    page.getByLabel("Max trade (USDC)", { exact: true }),
  ).toHaveValue("100");
  await expect(
    page.getByLabel("Daily loss threshold (%)", { exact: true }),
  ).toHaveValue("2.5");
  await expect(
    page.getByLabel("Approval required above (USDC)", { exact: true }),
  ).toHaveValue("80");
  await expect(page.getByLabel("Allowed market")).toHaveValue("ETH/USDC");
  check(
    "Intent text populates market, capital, position, trade, approval and daily-loss fields with disclosed conversion",
  );
  await page
    .getByRole("button", { name: "Tracy Copilot", exact: true })
    .click();
  await page
    .getByLabel("Ask Tracy", { exact: true })
    .fill("Set capital to 3000 USDC and approval above 90 USDC");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Apply to draft & open form" }),
  ).toBeVisible();
  await expect(
    page.getByLabel("Paper capital (USDC)", { exact: true }),
  ).toHaveValue("2000");
  await page.screenshot({
    path: new URL("proposed-changes.png", out).pathname,
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Apply to draft & open form" })
    .click();
  await expect(
    page.getByLabel("Paper capital (USDC)", { exact: true }),
  ).toHaveValue("3000");
  await expect(
    page.getByLabel("Approval required above (USDC)", { exact: true }),
  ).toHaveValue("90");
  check("Copilot proposes a diff; the form changes only after Apply");
  await page.getByLabel("Ask Tracy", { exact: true }).fill("Open guardrails");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(page).toHaveURL(base + "/infrastructure");
  await expect(
    page.getByRole("complementary", { name: "Tracy Copilot" }),
  ).toBeVisible();
  await page
    .getByRole("link", { name: "Help for this page", exact: true })
    .click();
  await expect(page).toHaveURL(base + "/help/guardrails");
  await expect(
    page
      .getByRole("heading", {
        name: "Guardrails and actual policy checks",
        exact: true,
      })
      .first(),
  ).toBeVisible();
  await expect(
    page.getByRole("complementary", { name: "Tracy Copilot" }),
  ).toBeVisible();
  await page
    .getByLabel("Ask Tracy", { exact: true })
    .fill("Что значит Replay next 24 candles?");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(page.locator(".copilot-message.assistant").last()).toContainText(
    "24 часа",
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByLabel("Ask Tracy", { exact: true })).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 1,
    ),
  ).toBe(true);
  await page.screenshot({
    path: new URL("copilot-mobile.png", out).pathname,
    fullPage: true,
  });
  check(
    "Navigation, contextual handbook, persistent sidebar chat and Russian replay explanation work on desktop/mobile",
  );
  await page.getByRole("button", { name: "Close Copilot" }).click();
  await page.setViewportSize({ width: 1600, height: 1100 });
  await page.goto(base + "/agents/new");
  // Existing draft is intentionally preserved when navigating through help.
  await page.getByRole("button", { name: "Suggest guardrails" }).click();
  await page
    .getByLabel("Agent name", { exact: true })
    .fill("Copilot reviewed recipe");
  await page.getByRole("button", { name: "Continue to test" }).click();
  await page.getByRole("button", { name: "Run backtests & checks" }).click();
  await expect(
    page.getByText("12/12 guardrail checks passed", { exact: true }),
  ).toBeVisible();
  await page
    .getByText("Binance source, exact candles & provenance", { exact: true })
    .click();
  const sourceHref = await page
    .getByRole("link", { name: "Download candles & source metadata" })
    .getAttribute("href");
  const source = await (await context.request.get(base + sourceHref)).json();
  expect(source.provider).toBe("Binance Spot");
  expect(source.synthetic).toBe(false);
  expect(source.bars.length).toBe(384);
  await page
    .getByText("View input, expectation & actual result", { exact: true })
    .first()
    .click();
  await page.screenshot({
    path: new URL("guardrail-evidence.png", out).pathname,
    fullPage: true,
  });
  await page.getByRole("button", { name: "Review deployment" }).click();
  await page
    .getByLabel(
      "I reviewed the intent, limits and test results. I authorize this paper deployment.",
    )
    .check();
  await page.getByRole("button", { name: "Deploy paper agent" }).click();
  await expect(
    page.getByText("Your agent has not executed yet.", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Replay next 24 candles" }),
  ).toBeVisible();
  const sid = new URL(page.url()).pathname.split("/").at(-1);
  const detail = await (
    await context.request.get(base + "/v1/strategies/" + sid)
  ).json();
  expect(detail.performance.verified_trades).toBe(0);
  expect(detail.performance.live_return).toBe(null);
  expect(detail.performance.deployment.step).toBe(0);
  expect(
    (
      await (
        await context.request.get(base + "/v1/strategies/" + sid + "/tests")
      ).json()
    ).items.length,
  ).toBe(3);
  check(
    "Actual candles export, twelve policy scenarios, three stored tests and zero execution at creation verified",
  );
  await page
    .getByRole("button", { name: "Publish agent", exact: true })
    .click();
  await expect(
    page.getByRole("dialog", { name: "Agent publication" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Confirm publication", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Manage publication", exact: true }),
  ).toBeVisible();
  // Real publication must become discoverable on the new public homepage.
  await page.goto(base + "/");
  await expect(
    page.locator('a[href="/exchange/strategies/' + sid + '"]'),
  ).toBeVisible();
  check("Published agent is discoverable on the marketplace homepage");
  await page.goto(base + "/exchange/strategies/" + sid);
  await page
    .getByRole("link", { name: "Test this agent with my limits" })
    .click();
  await page.getByRole("button", { name: "Suggest guardrails" }).click();
  await expect(
    page.getByText(
      /This copy gets its own identity and empty execution history/,
    ),
  ).toBeVisible();
  // Remove the local QA publication after testing its real public routes.
  const csrf = signup
    ? (await (await context.request.get(base + "/v1/auth/me")).json())
        .csrf_token
    : "";
  expect(
    (
      await context.request.put(
        base + "/v1/strategies/" + sid + "/publication",
        { headers: { "X-CSRF-Token": csrf }, data: { listed: false } },
      )
    ).ok(),
  ).toBe(true);
  check(
    "Visible publication with disclosure and marketplace-to-private-agent flow verified; QA listing removed",
  );
  expect(errors).toEqual([]);
  report.passed = true;
} catch (e) {
  report.passed = false;
  report.error = String(e);
  await page.screenshot({
    path: new URL("failure.png", out).pathname,
    fullPage: true,
  });
  throw e;
} finally {
  report.errors = errors;
  await fs.writeFile(
    new URL("report.json", out),
    JSON.stringify(report, null, 2),
  );
  await browser.close();
}
