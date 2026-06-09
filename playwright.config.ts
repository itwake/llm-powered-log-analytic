import { defineConfig, devices } from "@playwright/test";

const isCI = Boolean(process.env.CI);

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 120_000,
  expect: {
    timeout: 10_000,
  },
  fullyParallel: false,
  retries: isCI ? 1 : 0,
  workers: 1,
  reporter: isCI ? [["list"], ["html", {open: "never"}]] : "list",
  use: {
    baseURL: "http://localhost:3000",
    headless: true,
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
    trace: "on-first-retry",
  },
  webServer: [
    {
      command:
        "python -m uvicorn app.main:app --app-dir apps/api --host 127.0.0.1 --port 8000",
      url: "http://127.0.0.1:8000/docs",
      reuseExistingServer: !isCI,
      timeout: 120_000,
      env: {
        LOGAN_STORE_BACKEND: "memory",
        LOGAN_OBJECT_STORE_BACKEND: "local",
        LOGAN_LOCAL_OBJECT_STORE_DIR: ".logan/e2e-object-store",
        LOGAN_RATE_LIMIT_ENABLED: "false",
        LOGAN_METRICS_ENABLED: "true",
        LOGAN_SECRET_KEY: "e2e-local-secret",
        LOGAN_CREDENTIAL_ENCRYPTION_KEY: "e2e-local-credential-key",
        LOGAN_LLM_PROVIDER: "mock",
        LOGAN_ANALYSIS_ORCHESTRATOR: "local",
        LOGAN_ANALYTICS_SINKS_ENABLED: "false",
        LOGAN_EXTERNAL_ANALYTICS_QUERIES_ENABLED: "false",
        PYTHONUNBUFFERED: "1",
      },
    },
    {
      command: "pnpm --filter @logan/web dev --hostname 127.0.0.1 --port 3000",
      url: "http://127.0.0.1:3000",
      reuseExistingServer: !isCI,
      timeout: 120_000,
      env: {
        NEXT_PUBLIC_API_BASE_URL: "http://localhost:8000",
      },
    },
  ],
  projects: [
    {
      name: "chromium",
      use: {...devices["Desktop Chrome"]},
    },
  ],
});
