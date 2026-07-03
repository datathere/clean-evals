import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, devices } from "@playwright/test";

const PORT = 8123;
const FAKE_PROVIDER_PORT = 11499;

const here = path.dirname(fileURLToPath(import.meta.url));

// The backend runs from .e2e/ so its SQLite database and artifacts stay
// isolated from any development instance. The local adapter points at the
// fake provider server (below) so the golden-path test spends nothing.
const e2eDir = path.join(here, ".e2e");
mkdirSync(e2eDir, { recursive: true });

// Override locally when `python` is not the interpreter with clean-evals
// installed, e.g.
//   E2E_SERVER_COMMAND="../.venv/Scripts/clean-evals migrate && ../.venv/Scripts/clean-evals serve --port 8123"
const serverCommand =
  process.env.E2E_SERVER_COMMAND ??
  "python -m clean_evals.cli migrate && " +
    `python -m clean_evals.cli serve --host 127.0.0.1 --port ${PORT}`;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `node ${path.join(here, "e2e", "fake-provider.mjs")}`,
      env: { FAKE_PROVIDER_PORT: String(FAKE_PROVIDER_PORT) },
      url: `http://127.0.0.1:${FAKE_PROVIDER_PORT}/v1/models`,
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
    },
    {
      command: serverCommand,
      cwd: e2eDir,
      env: { CLEAN_EVALS_LOCAL_BASE_URL: `http://127.0.0.1:${FAKE_PROVIDER_PORT}/v1` },
      url: `http://127.0.0.1:${PORT}/api/v1/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
});
