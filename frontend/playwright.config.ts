import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  use: {
    baseURL: "http://127.0.0.1:1420",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: "uv run --project .. --no-default-groups --group studio --group music --extra cuda woosh-studio-api",
      url: "http://127.0.0.1:8765/api/v1/health",
      reuseExistingServer: true,
      timeout: 120_000,
    },
    {
      command: "npm run dev",
      url: "http://127.0.0.1:1420",
      reuseExistingServer: true,
      timeout: 120_000,
    },
  ],
});
