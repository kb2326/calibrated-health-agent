// Publishable screenshots and a screen recording of the web app in demo mode (synthetic data,
// real Gemini agent). Run against `cha-web --demo --port 8790`:
//   node e2e/capture.mjs
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";

const BASE = process.env.CAPTURE_URL ?? "http://127.0.0.1:8790";
const OUT = "../../docs/images";
const QUESTION = process.env.CAPTURE_QUESTION ?? "How did I sleep this week?";
mkdirSync(OUT, { recursive: true });

async function run(page, { slow = false } = {}) {
  await page.goto(BASE + "/");
  await page.getByText("demo data").waitFor();
  await page.waitForTimeout(slow ? 1200 : 300);
  const box = page.getByLabel("Your question");
  if (slow) await box.pressSequentially(QUESTION, { delay: 45 });
  else await box.fill(QUESTION);
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await page.getByTestId("live").filter({ hasText: "Answer ready" }).waitFor({ timeout: 180_000 });
  await page.waitForTimeout(slow ? 1500 : 500);
  const chip = page.getByRole("button", { name: /^Open receipt r-[0-9a-f]{10}$/ }).first();
  await chip.click();
  const panel = page.getByRole("complementary", { name: "Receipt" });
  await panel.getByRole("button", { name: "Re-run" }).waitFor();
  await page.waitForTimeout(slow ? 1200 : 300);
  await panel.getByRole("button", { name: "Re-run" }).click();
  await panel.getByText(/Matches|Differs|Data changed/).waitFor({ timeout: 60_000 });
  await page.waitForTimeout(slow ? 2500 : 400);
}

const browser = await chromium.launch();
const shots = [
  { name: "web-desktop-dark", viewport: { width: 1440, height: 900 }, colorScheme: "dark", deviceScaleFactor: 2 },
  { name: "web-desktop-light", viewport: { width: 1440, height: 900 }, colorScheme: "light", deviceScaleFactor: 2 },
  { name: "web-phone-dark", viewport: { width: 390, height: 844 }, colorScheme: "dark", deviceScaleFactor: 3, isMobile: true, hasTouch: true },
];
for (const s of shots) {
  const ctx = await browser.newContext({ ...s, name: undefined });
  const page = await ctx.newPage();
  await run(page);
  if (s.isMobile) {
    // phone: one shot of the answer, one of the receipt sheet
    await page.screenshot({ path: `${OUT}/${s.name}-receipt.png` });
    await page.getByRole("button", { name: "Close" }).click();
    await page.getByTestId("metric-card").first().scrollIntoViewIfNeeded().catch(() => {});
  }
  await page.screenshot({ path: `${OUT}/${s.name}.png`, fullPage: !s.isMobile });
  console.log("saved", s.name);
  await ctx.close();
}

// The recording: desktop, dark, typed question, the agent's steps, the answer, a receipt re-run.
const vctx = await browser.newContext({
  viewport: { width: 1280, height: 800 }, colorScheme: "dark",
  recordVideo: { dir: `${OUT}/video`, size: { width: 1280, height: 800 } },
});
const vpage = await vctx.newPage();
await run(vpage, { slow: true });
await vctx.close();
console.log("saved video", await vpage.video()?.path());
await browser.close();
