import { defineConfig, devices } from "@playwright/test";
import { fileURLToPath } from "node:url";

const repo = fileURLToPath(new URL("../..", import.meta.url));
const script = fileURLToPath(new URL("./e2e/script.json", import.meta.url));
const PORT = 8781;

// One server in demo mode (synthetic fixture) with a scripted model: no network, no keys.
export default defineConfig({
  testDir: "e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: { baseURL: `http://127.0.0.1:${PORT}`, trace: "retain-on-failure" },
  projects: [
    { name: "desktop-dark", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 }, colorScheme: "dark" } },
    { name: "desktop-light", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 }, colorScheme: "light" } },
    { name: "phone-dark", use: { ...devices["Pixel 7"], viewport: { width: 390, height: 844 }, colorScheme: "dark" } },
  ],
  webServer: {
    command: `uv run cha-web --demo --test-model --port ${PORT}`,
    cwd: repo,
    env: { CHA_WEB_FAKE_SCRIPT: script, CHA_DATA_MODE: "synthetic" },
    url: `http://127.0.0.1:${PORT}/api/health`,
    timeout: 180_000,
    reuseExistingServer: false,
  },
});
