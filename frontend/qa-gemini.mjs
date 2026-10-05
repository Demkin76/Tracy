// Opt-in live provider smoke test. Uses server-held Gemini credentials only.
import { chromium, expect } from "@playwright/test";
import fs from "node:fs/promises";
const base = process.env.TRACY_URL || "http://127.0.0.1:8000";
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
  await page.goto(base + "/help/replay");
  await page
    .getByRole("button", { name: "Tracy Copilot", exact: true })
    .click();
  await page.getByRole("checkbox", { name: /Use Gemini/ }).check();
  await page
    .getByLabel("Ask Tracy")
    .fill(
      "Кратко по-русски: что делает Replay next 24 candles? Это реальные сделки?",
    );
  const responsePromise = page.waitForResponse(
    (r) =>
      r.url().endsWith("/v1/copilot/message") &&
      r.request().method() === "POST",
    { timeout: 60000 },
  );
  await page.getByRole("button", { name: "Send", exact: true }).click();
  const response = await responsePromise;
  const body = await response.json();
  expect(response.ok(), body.detail || "Gemini response").toBe(true);
  expect(body.mode).toBe("ai");
  expect(body.answer).toMatch(/[а-яА-Я]/);
  await expect(page.locator(".copilot-message.assistant").last()).toBeVisible();
  await fs.mkdir(new URL("../data/qa-gemini/", import.meta.url), {
    recursive: true,
  });
  await page.screenshot({
    path: new URL("../data/qa-gemini/copilot.png", import.meta.url).pathname,
    fullPage: true,
  });
  await fs.writeFile(
    new URL("../data/qa-gemini/report.json", import.meta.url),
    JSON.stringify(
      { passed: true, mode: body.mode, answer: body.answer },
      null,
      2,
    ),
  );
  console.log(
    "Passed: visible Gemini opt-in, actual Russian model response in sidebar, no client-held API key",
  );
} finally {
  await browser.close();
}
