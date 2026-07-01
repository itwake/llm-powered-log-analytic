import { expect, test, type Page } from "@playwright/test";

const SSO_USERNAME = "playwright-sso";

async function signInThroughUi(page: Page) {
  await page.goto("/login");
  await page.waitForURL(/\/cases$/, {timeout: 30_000});
  await expect(page.getByText(SSO_USERNAME)).toBeVisible();
}

async function clickApply(page: Page) {
  const apply = page.getByRole("button", {name: "Apply"});
  await apply.click();
  await expect(apply).toBeEnabled();
}

async function expectFirstTableRow(page: Page) {
  await expect(page.locator("tbody tr").first()).toBeVisible({timeout: 30_000});
}

test("auth smoke redirects through SSO and establishes a session", async ({page}) => {
  await signInThroughUi(page);
  await page.context().clearCookies();
  await page.goto("/cases");
  await page.waitForURL(/\/cases$/, {timeout: 30_000});
  await expect(page.getByText(SSO_USERNAME)).toBeVisible();
});

test("sample case analysis can be explored through report views", async ({page}) => {
  test.setTimeout(180_000);

  await signInThroughUi(page);
  await page.goto("/cases");
  await expect(page.getByRole("heading", {name: "Cases"})).toBeVisible();

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

  await page.getByRole("button", {name: "Edit"}).click();
  await page.getByLabel("Summary markdown").fill("# Canceled Candidate Summary\n\nThis should not persist.");
  await page.getByLabel("Customer update markdown").fill("Canceled customer update.");
  await page.getByRole("button", {name: "Cancel"}).click();
  await expect(page.getByText("Incident Diagnosis Summary")).toBeVisible();

  await page.getByRole("button", {name: "Edit"}).click();
  await page
    .getByLabel("Summary markdown")
    .fill("# E2E Edited Candidate Summary\n\nCandidate evidence remains available after editing.");
  await page
    .getByLabel("Customer update markdown")
    .fill("Customer-facing update edited by Playwright.");
  await page.getByRole("button", {name: "Save"}).click();
  await expect(page.getByText("Causal summary saved")).toBeVisible({timeout: 30_000});
  await expect(page.getByText("E2E Edited Candidate Summary")).toBeVisible();
  await expect(page.getByText("Customer-facing update edited by Playwright.")).toBeVisible();
  await expect(page.getByText("Edited", {exact: true})).toBeVisible();

  await page.getByRole("button", {name: "Export Markdown"}).click();
  await expect(page.getByText(/markdown export ready:/)).toBeVisible({timeout: 30_000});
});
