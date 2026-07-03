import { expect, test } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const fixturesDir = path.join(path.dirname(fileURLToPath(import.meta.url)), "fixtures");

// The whole money flow, against the fake provider (zero API cost):
// upload -> generate candidates -> rate -> lock golden -> run -> leaderboard.
test("golden path: upload, generate, lock, run, results", async ({ page }) => {
  test.slow(); // generation + inline run take a few seconds each

  // 1. Upload a small dataset.
  await page.goto("/builder");
  await page.getByRole("button", { name: /Same setup, different data/ }).click();
  await page
    .getByLabel("System prompt")
    .fill("Classify the sentiment as positive, negative, or neutral.");
  const name = `e2e-golden-${Date.now()}`;
  await page.getByLabel("Name", { exact: true }).fill(name);
  await page.getByLabel("Version", { exact: true }).fill("v1");
  await page.locator('input[type="file"]').setInputFiles(path.join(fixturesDir, "sentiment.csv"));
  await page.getByRole("button", { name: "Create dataset" }).click();
  await expect(page).toHaveURL(/\/builder\/\d+/);

  // 2. Pick the fake local model and generate candidates.
  await page.getByRole("button", { name: "local/fake-1", exact: false }).first().click();
  await page.getByRole("button", { name: /^(Generate|Regenerate)$/ }).click();

  // Candidate outputs appear per case once generation finishes.
  await expect(page.getByRole("button", { name: /Use as golden/ }).first()).toBeVisible({
    timeout: 30_000,
  });

  // 3. Rate and lock a golden answer for every case.
  const useButtons = page.getByRole("button", { name: /Use as golden/ });
  let remaining = await useButtons.count();
  expect(remaining).toBeGreaterThan(0);
  while (remaining > 0) {
    const btn = useButtons.first();
    await btn.scrollIntoViewIfNeeded();
    await btn.click();
    // Locking removes this case's "Use as golden" button.
    await expect(async () => {
      expect(await useButtons.count()).toBeLessThan(remaining);
    }).toPass({ timeout: 10_000 });
    remaining = await useButtons.count();
  }

  // 4. The dataset is golden; run the eval inline.
  await expect(page.getByText(/Golden dataset/)).toBeVisible({ timeout: 10_000 });
  await page.getByRole("button", { name: "local/fake-1", exact: false }).first().click();
  await page.getByRole("button", { name: /^Run eval$/ }).click();

  // 5. The run finishes and navigates to the leaderboard.
  await expect(page).toHaveURL(/\/runs\/r_/, { timeout: 60_000 });
  await expect(page.getByText("Leaderboard")).toBeVisible();
  await expect(page.getByText("local/fake-1").first()).toBeVisible();
});
