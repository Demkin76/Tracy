// Browser-only fixtures exercise ranking edge cases. Nothing is written to Tracy's database.
import { chromium, expect } from "@playwright/test";
import fs from "node:fs/promises";
const base = process.env.TRACY_URL || "http://127.0.0.1:8000";
const out = new URL("../data/qa-marketplace-first/", import.meta.url);
await fs.mkdir(out, { recursive: true });
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
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
const report = { checks: [], errors };
const check = (x) => {
  report.checks.push(x);
  console.log(x);
};
try {
  // Exercise the real application unauthenticated before any fixture interception.
  await page.goto(base + "/");
  await expect(
    page.getByRole("heading", {
      name: "Compare agents. Inspect the evidence.",
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Welcome back." }),
  ).toHaveCount(0);
  const real = await (
    await context.request.get(base + "/v1/public/trading/strategies")
  ).json();
  await expect(page.locator(".strategy-card")).toHaveCount(real.items.length);
  await page.screenshot({
    path: new URL("marketplace.png", out).pathname,
    fullPage: true,
  });
  check(
    "Homepage is public marketplace with real public listing count; no login or builder gate",
  );
  await page.goto(base + "/explore");
  await expect(page).toHaveURL(base + "/");
  const nav = await page
    .locator(".public-nav nav a")
    .evaluateAll((as) => as.map((a) => a.getAttribute("href")));
  expect(new Set(nav).size).toBe(nav.length);
  expect(nav).toContain("/leaderboard");
  expect(nav).toContain("/developers");
  check(
    "Legacy explore redirects; marketplace, leaderboard, compare, studio and workspace have distinct destinations",
  );
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 1,
    ),
  ).toBe(true);
  await page.screenshot({
    path: new URL("marketplace-mobile.png", out).pathname,
    fullPage: true,
  });
  await page.setViewportSize({ width: 1440, height: 1000 });

  // Explicitly synthetic test fixtures, restricted to this browser context.
  let listings = [];
  await page.route("**/v1/public/trading/strategies", (route) =>
    route.fulfill({ json: { items: listings } }),
  );
  await page.goto(base + "/leaderboard");
  await expect(
    page.getByRole("heading", { name: "No eligible public runs yet" }),
  ).toBeVisible();
  function fixture(id, overrides = {}) {
    return {
      strategy_id: id,
      agent_id: id,
      name: "Test recipe " + id,
      agent_name: "Fixture " + id,
      market: "SOL/USDC",
      timeframe: "1h",
      version: 1,
      starting_capital: 1000,
      strategy_config: { runner: "momentum", fee_bps: 10, slippage_bps: 5 },
      health: { score: null, status: "WATCH" },
      performance: {
        live_return: 2,
        verified_trades: 12,
        deployment: { step: 96 },
        live: {
          max_drawdown: 1,
          closed_trade_count: 6,
          trade_count: 12,
          win_rate: 50,
        },
        replay_market_data: {
          provider: "test-only",
          period_start: 1700000000,
          period_end: 1700345600,
        },
      },
      ...overrides,
    };
  }
  const a = fixture("A"),
    b = fixture("B"),
    c = fixture("C"),
    incomplete = fixture("incomplete"),
    insufficient = fixture("insufficient"),
    unverified = fixture("unverified"),
    different = fixture("different-window"),
    cost = fixture("different-cost");
  b.performance.live_return = 1;
  b.performance.live.max_drawdown = 0.2;
  incomplete.performance.deployment.step = 24;
  insufficient.performance.live.closed_trade_count = 2;
  unverified.performance.verified_trades = 11;
  different.performance.replay_market_data.period_start += 3600;
  cost.strategy_config.fee_bps = 20;
  listings = [a, b, c, incomplete, insufficient, unverified, different, cost];
  await page.reload();
  const select = page.getByLabel("Benchmark group");
  await expect(select.locator("option")).toHaveCount(4); // prompt + three distinct eligible cohorts
  await select.selectOption({ index: 1 });
  await expect(page.locator("tbody tr")).toHaveCount(3);
  expect(
    await page.locator("tbody tr td:first-child").allTextContents(),
  ).toEqual(["1", "1", "3"]);
  expect(
    await page.locator("tbody tr td:nth-child(2) a").allTextContents(),
  ).toEqual(["Fixture A", "Fixture C", "Fixture B"]);
  await page.getByLabel("Rank by").selectOption("drawdown");
  expect(
    await page.locator("tbody tr td:nth-child(2) a").allTextContents(),
  ).toEqual(["Fixture B", "Fixture A", "Fixture C"]);
  check(
    "Browser fixtures: cohort isolation, minimum sample, completion, verification, return/drawdown order and tied ranks pass",
  );
  await page.goto(base + "/");
  await expect(page.locator(".strategy-card")).toHaveCount(8);
  await page.getByLabel("Evidence", { exact: true }).selectOption("ranked");
  await expect(page.locator(".strategy-card")).toHaveCount(5);
  await page
    .getByLabel("Search agents", { exact: true })
    .fill("different-window");
  await expect(page.locator(".strategy-card")).toHaveCount(1);
  await expect(
    page.getByRole("link", { name: "Test with my limits" }),
  ).toHaveAttribute("href", "/agents/new?source=different-window&version=1");
  check(
    "Marketplace filters work and instance handoff pins the selected version",
  );
  await page.unroute("**/v1/public/trading/strategies");
  const credentials = JSON.parse(
    await fs.readFile(
      new URL("../data/tracy-owner.json", import.meta.url),
      "utf8",
    ),
  );
  const login = await context.request.post(base + "/v1/auth/login", {
    data: { email: credentials.email, password: credentials.password },
  });
  expect(login.ok()).toBe(true);
  await page.goto(base + "/");
  await expect(
    page.getByRole("heading", {
      name: "Compare agents. Inspect the evidence.",
    }),
  ).toBeVisible();
  await page.goto(base + "/developers");
  await expect(
    page.getByRole("heading", { name: "Developer studio", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: new URL("developer-studio.png", out).pathname,
    fullPage: true,
  });
  await page.goto(base + "/overview");
  await expect(
    page.getByRole("heading", { name: "My trading workspace", exact: true }),
  ).toBeVisible();
  check(
    "Signed-in home stays marketplace; studio and personal overview remain distinct",
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
  await fs.writeFile(
    new URL("report.json", out),
    JSON.stringify(report, null, 2),
  );
  await browser.close();
}
