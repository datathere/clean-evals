import { expect, test } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const fixturesDir = path.join(path.dirname(fileURLToPath(import.meta.url)), "fixtures");

test("serves the app shell", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle(/clean-evals/);
  await expect(page.getByRole("heading", { name: "Datasets", exact: true })).toBeVisible();
});

test("lists the seeded sample datasets", async ({ page }) => {
  await page.goto("/datasets");
  await expect(page.getByText("sample-ticket-triage").first()).toBeVisible();
  await expect(page.getByText("sample-sentiment").first()).toBeVisible();
  await expect(page.getByText("sample-summaries").first()).toBeVisible();
});

test("navigates between pages", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Runs" }).click();
  await expect(page).toHaveURL(/\/runs/);
  await page.getByRole("link", { name: "Models" }).click();
  await expect(page).toHaveURL(/\/models/);
  await expect(page.getByRole("heading", { name: "Models", exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Schedules" }).click();
  await expect(page).toHaveURL(/\/schedules/);
});

test("models page lists the built-in providers", async ({ page }) => {
  await page.goto("/models");
  await expect(page.getByText(/anthropic/i).first()).toBeVisible();
  await expect(page.getByText(/openai/i).first()).toBeVisible();
});

test("upload wizard asks the request-shape question", async ({ page }) => {
  await page.goto("/builder");
  await expect(page.getByRole("heading", { name: "New dataset" })).toBeVisible();
  await expect(page.getByText("How does your app talk to the model?")).toBeVisible();
  await expect(page.getByRole("button", { name: /Same setup, different data/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /Complete requests/ })).toBeVisible();
});

test("creates a dataset through the upload wizard", async ({ page }) => {
  await page.goto("/builder");

  await page.getByRole("button", { name: /Same setup, different data/ }).click();
  await page
    .getByLabel("System prompt")
    .fill("Classify the ticket as billing, fraud, or technical. Reply with the category only.");

  // Unique name: the e2e database persists across local runs and
  // (name, version) pairs are unique.
  const name = `e2e-tickets-${Date.now()}`;
  await page.getByLabel("Name", { exact: true }).fill(name);
  await page.getByLabel("Version", { exact: true }).fill("v1");
  await page.locator('input[type="file"]').setInputFiles(path.join(fixturesDir, "tickets.csv"));
  await page.getByRole("button", { name: "Create dataset" }).click();

  // Upload navigates to the workspace for the new dataset.
  await expect(page).toHaveURL(/\/builder\/\d+/);
  await expect(page.getByText("ticket_001").first()).toBeVisible();
  await expect(page.getByText("ticket_002").first()).toBeVisible();
});
