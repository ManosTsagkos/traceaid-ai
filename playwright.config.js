const { defineConfig, devices } = require("@playwright/test");

const python = process.env.TRACEAID_TEST_PYTHON || "python";
module.exports = defineConfig({
  testDir: "./tests/browser",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: 2,
  reporter: "list",
  use: {
    ...devices["Desktop Chrome"],
    channel: process.env.TRACEAID_BROWSER_CHANNEL || undefined,
    trace: "retain-on-failure"
  },
  webServer: [
    {
      command: `"${python}" -m http.server 18767 --bind 127.0.0.1 --directory site`,
      url: "http://127.0.0.1:18767",
      timeout: 15000,
      reuseExistingServer: !process.env.CI
    },
    {
      command: `"${python}" -m uvicorn traceaid.main:app --host 127.0.0.1 --port 18768`,
      url: "http://127.0.0.1:18768/api/health",
      timeout: 15000,
      reuseExistingServer: !process.env.CI,
      env: { OPENAI_API_KEY: "", TRACEAID_ENABLE_LIVE_PROBES: "false" }
    }
  ]
});
