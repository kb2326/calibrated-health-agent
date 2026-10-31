import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test("ask → stream → timeline → receipt → re-run matches → metric card → approve a fact", async ({ page }) => {
  const cspErrors: string[] = [];
  page.on("console", (m) => { if (m.type() === "error" && /Content Security Policy/i.test(m.text())) cspErrors.push(m.text()); });

  await page.goto("/");
  await expect(page.getByText("demo data")).toBeVisible();

  await page.getByLabel("Your question").fill("How has my resting heart rate been?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();

  const timeline = page.getByRole("list", { name: "Agent at work" });
  await expect(timeline.getByText(/Running a query/)).toBeVisible();
  await expect(page.getByText(/resting heart rate for the last week/)).toBeVisible();
  await expect(page.getByTestId("metric-card")).toBeVisible();

  const chip = page.getByRole("button", { name: /^Open receipt r-[0-9a-f]{10}$/ }).first();
  await chip.click();
  const panel = page.getByRole("complementary", { name: "Receipt" });
  await expect(panel.getByText("SQL over daily resting heart rate")).toBeVisible();
  await panel.getByRole("button", { name: "Re-run" }).click();
  await expect(panel.getByText("Matches")).toBeVisible();

  const axe = await new AxeBuilder({ page }).analyze();
  const serious = axe.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(serious.map((v) => `${v.id}: ${v.nodes.length}`)).toEqual([]);

  await panel.getByRole("button", { name: "Close" }).click();
  await page.getByLabel("Your question").fill("Remember that I train on Tuesdays");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  const card = page.getByRole("group", { name: "Save a memory?" });
  await expect(card).toBeVisible();
  await expect(card.getByText("I train on Tuesdays")).toBeVisible();
  await card.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText(/I'll remember that you train on Tuesdays/)).toBeVisible();

  expect(cspErrors).toEqual([]);
});

test("scoreboard says not yet and passes axe", async ({ page }) => {
  await page.goto("/scoreboard/");
  await expect(page.getByText("Not yet")).toBeVisible();
  const axe = await new AxeBuilder({ page }).analyze();
  expect(axe.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => v.id)).toEqual([]);
});
