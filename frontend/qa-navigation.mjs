import { chromium, expect } from "@playwright/test";
import fs from "node:fs/promises";

const base = process.env.TRACY_URL || "http://127.0.0.1:8000";
const out = new URL("../data/qa-navigation/", import.meta.url);
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
const errors = [],
  failures = [],
  pages = [];
page.on("pageerror", (e) => errors.push(e.message));
page.on("response", (r) => {
  if (new URL(r.url()).origin === base && r.status() >= 400)
    failures.push([r.status(), r.url()]);
});
const report = {
  started_at: new Date().toISOString(),
  pages,
  errors,
  failures,
};
try {
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
  await page.goto(base + "/overview");
  await page.waitForLoadState("networkidle");
  const nav = await page.locator(".sidebar nav a").evaluateAll((links) =>
    links.map((a) => ({
      path: a.getAttribute("href"),
      label: a.textContent.trim(),
    })),
  );
  expect(nav.length).toBeGreaterThan(8);
  expect(new Set(nav.map((a) => a.path)).size).toBe(nav.length);
  const links = new Set();
  for (const { path, label } of nav) {
    await page.goto(base + path);
    await page.waitForLoadState("networkidle");
    const heading = (await page.locator("h1").first().innerText()).trim();
    expect(heading.length).toBeGreaterThan(0);
    expect(
      await page.getByText("Page not found.", { exact: false }).count(),
    ).toBe(0);
    const anchors = await page
      .locator("a[href]")
      .evaluateAll((as) => as.map((a) => a.getAttribute("href")));
    expect(
      anchors.filter((h) => !h || h === "#" || h.startsWith("javascript:")),
    ).toEqual([]);
    anchors.filter((h) => h.startsWith("/")).forEach((h) => links.add(h));
    pages.push({ path, label, heading });
    await page.screenshot({
      path: new URL(label.replaceAll(" ", "-") + ".png", out).pathname,
      fullPage: true,
    });
    console.log(label + ": " + heading);
  }
  expect(new Set(pages.map((p) => p.heading)).size).toBe(pages.length);
  for (const path of links) {
    const response = await context.request.get(base + path);
    expect(response.ok(), path).toBe(true);
    if (path === "/docs" || path === "/openapi.json") continue;
    await page.goto(base + path);
    await page.waitForLoadState("networkidle");
    expect(
      await page.getByText("Page not found.", { exact: false }).count(),
      path,
    ).toBe(0);
    expect(await page.locator("h1").count(), path).toBeGreaterThan(0);
    const tab = new URL(base + path).searchParams.get("tab");
    if (tab) await expect(page.locator(".tabs button.active")).toHaveText(tab);
  }
  expect(errors).toEqual([]);
  expect(failures).toEqual([]);
  report.passed = true;
  report.links_checked = [...links];
  console.log(
    "Passed: " +
      pages.length +
      " distinct sections, " +
      links.size +
      " links, no browser/API errors",
  );
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
