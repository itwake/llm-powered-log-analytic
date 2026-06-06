import { expect, test, type Page, type TestInfo } from "@playwright/test";

type TestUser = {
  email: string;
  username: string;
  password: string;
};

function uniqueUser(testInfo: TestInfo, label: string): TestUser {
  const suffix = `${label}-${Date.now()}-${testInfo.workerIndex}-${Math.random()
    .toString(36)
    .slice(2, 8)}`;
  return {
    email: `e2e-${suffix}@example.com`,
    username: `e2e-${suffix}`,
    password: "Password123!",
  };
}

async function registerThroughUi(page: Page, user: TestUser) {
  await page.goto("/register");
  await expect(page.getByRole("heading", {name: "Register"})).toBeVisible();
  await page.getByLabel("Email").fill(user.email);
  await page.getByLabel("Username").fill(user.username);
  await page.getByLabel("Full name").fill("Playwright Engineer");
  await page.getByLabel("Password").fill(user.password);
  await Promise.all([
    page.waitForURL(/\/cases$/, {timeout: 30_000}),
    page.getByRole("button", {name: "Create account"}).click(),
  ]);
  await expect(page.getByText(user.username)).toBeVisible();
}

async function signInThroughUi(page: Page, user: TestUser) {
  await page.goto("/login");
  await expect(page.getByRole("heading", {name: "Sign in"})).toBeVisible();
  await page.getByLabel("Email or username").fill(user.username);
  await page.getByLabel("Password").fill(user.password);
  await Promise.all([
    page.waitForURL(/\/cases$/, {timeout: 30_000}),
    page.getByRole("button", {name: "Sign in"}).click(),
  ]);
  await expect(page.getByText(user.username)).toBeVisible();
}

async function clickApply(page: Page) {
  const apply = page.getByRole("button", {name: "Apply"});
  await apply.click();
  await expect(apply).toBeEnabled();
}

async function expectFirstTableRow(page: Page) {
  await expect(page.locator("tbody tr").first()).toBeVisible({timeout: 30_000});
}

test("auth smoke shows login errors and accepts an existing account", async ({page}, testInfo) => {
  const user = uniqueUser(testInfo, "auth");

  await page.goto("/login");
  await page.getByLabel("Email or username").fill(`missing-${user.username}`);
  await page.getByLabel("Password").fill("wrong-password");
  await page.getByRole("button", {name: "Sign in"}).click();
  await expect(page.getByText("invalid credentials")).toBeVisible();

  await registerThroughUi(page, user);
  await page.context().clearCookies();
  await signInThroughUi(page, user);
});

test("sample case analysis can be explored through report views", async ({page}, testInfo) => {
  test.setTimeout(180_000);

  await page.goto("/cases");
  await expect(page.getByRole("heading", {name: "Cases"})).toBeVisible();
  await expect(page.getByRole("link", {name: "Sign in"})).toBeVisible();

  const user = uniqueUser(testInfo, "flow");
  await page.getByRole("link", {name: "Sign in"}).click();
  await page.getByRole("link", {name: "Register"}).click();
  await registerThroughUi(page, user);

  await page.getByRole("link", {name: "New case", exact: true}).click();
  await expect(page.getByRole("heading", {name: "New Case"})).toBeVisible();

  const caseTitle = `E2E checkout incident ${Date.now()}`;
  await page.getByLabel("Title").fill(caseTitle);
  await page
    .getByLabel("Issue description")
    .fill("Checkout requests are failing after upstream authentication timeouts.");
  await page.getByLabel("Product").fill("LogAn Storefront");
  await page.getByLabel("Service").fill("checkout");
  await page.getByLabel("Environment").fill("staging");

  await Promise.all([
    page.waitForURL(/\/cases\/[^/]+\/runs\/[^/]+\/summary$/, {timeout: 120_000}),
    page.getByRole("button", {name: "Create and start sample/local analysis"}).click(),
  ]);

  await expect(page.getByRole("heading", {name: "Data Summary"})).toBeVisible();
  await expect(page.getByText("Raw lines")).toBeVisible();
  await expect(page.getByText("Offending templates")).toBeVisible();
  await expect(page.getByText("Review reduction")).toBeVisible();
  await expectFirstTableRow(page);

  await page.getByLabel("Signal").selectOption("error");
  await clickApply(page);
  await expectFirstTableRow(page);
  await expect(page.locator("tbody tr").filter({hasText: "error"}).first()).toBeVisible();

  await Promise.all([
    page.waitForURL(/\/temporal$/, {timeout: 60_000}),
    page.getByRole("link", {name: "Temporal View"}).click(),
  ]);
  await expect(page.getByRole("heading", {name: "Temporal View"})).toBeVisible({timeout: 30_000});
  await expect(page.getByTestId("temporal-echarts")).toBeVisible();
  await page.getByLabel("Window").selectOption("300");
  await page.getByLabel("Group").selectOption("service");
  await clickApply(page);
  const temporalChart = page.getByTestId("temporal-echarts");
  await expect(temporalChart).toBeVisible();
  await temporalChart.click();
  await expect(page.getByTestId("temporal-selection-summary")).toContainText("logs");
  await Promise.all([
    page.waitForURL(/\/logs\?window_start=.*window_end=/, {timeout: 30_000}),
    page.getByRole("link", {name: "Open in Tabular Logs"}).click(),
  ]);

  await expect(page.getByRole("heading", {name: "Tabular Logs"})).toBeVisible();
  await expect(page.getByTestId("logs-window-filter")).toBeVisible();
  await expectFirstTableRow(page);
  await page.getByLabel("Keyword").fill("checkout");
  await clickApply(page);
  await expectFirstTableRow(page);
  await expect(page.getByText("/checkout").first()).toBeVisible();

  await Promise.all([
    page.waitForURL(/\/causal-graph$/, {timeout: 60_000}),
    page.getByRole("link", {name: "Causal Graph"}).click(),
  ]);
  await expect(page.getByRole("heading", {name: "Causal Graph"})).toBeVisible({timeout: 30_000});
  await expect(page.getByTestId("cytoscape-graph")).toBeVisible();
  await page.getByTestId("cytoscape-graph").click();
  await expect(page.getByTestId("causal-detail-panel")).toBeVisible();
  await expect(page.getByRole("heading", {name: "Root Cause Candidates"})).toBeVisible();
  await page.getByLabel(/Min confidence/).fill("0.05");
  await clickApply(page);
  await expect(page.getByTestId("cytoscape-graph")).toBeVisible();
  await expect(page.getByRole("heading", {name: "Candidate Edges"})).toBeVisible();

  await Promise.all([
    page.waitForURL(/\/causal-summary$/, {timeout: 60_000}),
    page.getByRole("link", {name: "Causal Summary"}).click(),
  ]);
  await expect(page.getByRole("heading", {name: "Causal Summary"})).toBeVisible({timeout: 30_000});
  await expect(page.getByText("Incident Diagnosis Summary")).toBeVisible();
  await expect(page.getByText("Confidence", {exact: true})).toBeVisible();
  await expect(page.getByText("Evidence refs", {exact: true})).toBeVisible();
  await expect(page.getByRole("heading", {name: "Next Actions"})).toBeVisible();
  await expect(page.getByRole("heading", {name: "Evidence"})).toBeVisible();
});
