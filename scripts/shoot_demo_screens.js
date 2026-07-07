/* Tutorial screenshot set. Usage: node shoot2.js <caseId> <runId> <outDir> */
const { chromium } = require("@playwright/test");
const fs = require("fs");

const [caseId, runId, outDir] = process.argv.slice(2);
const base = "http://localhost:3000";
const run = `${base}/cases/${caseId}/runs/${runId}`;

(async () => {
  fs.mkdirSync(outDir, { recursive: true });
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const shot = async (name, ms = 1500) => {
    await page.waitForTimeout(ms);
    await page.screenshot({ path: `${outDir}/${name}.png` });
    console.log("shot", name);
  };

  await page.goto(`${base}/login`, { waitUntil: "domcontentloaded" });
  await page.waitForURL(/\/cases/, { timeout: 30000 });
  await shot("01-cases-list");

  await page.goto(`${base}/cases/new`, { waitUntil: "networkidle" });
  await shot("02-new-case");

  await page.goto(`${base}/cases/${caseId}`, { waitUntil: "networkidle" });
  await shot("03-case-workspace");
  await page.evaluate(() => window.scrollTo(0, 1100));
  await shot("03b-uploads-runs", 800);

  await page.goto(`${run}/summary`, { waitUntil: "networkidle" });
  await shot("04-summary");

  await page.goto(`${run}/temporal`, { waitUntil: "networkidle" });
  await page.evaluate(() => window.scrollTo(0, 260));
  await shot("05-temporal", 2600);

  await page.goto(`${run}/logs`, { waitUntil: "networkidle" });
  await shot("06-logs", 2200);

  const search = page.locator('input').first();
  await search.fill("user_email");
  await search.press("Enter");
  await shot("07-logs-redaction", 2200);

  await search.fill("SocketTimeoutException");
  await search.press("Enter");
  await shot("07b-logs-stacktrace", 2200);

  await page.goto(`${run}/causal-graph`, { waitUntil: "networkidle" });
  await shot("08-causal-graph", 4500);

  await page.goto(`${run}/causal-summary`, { waitUntil: "networkidle" });
  await shot("09-causal-summary", 1800);
  await page.evaluate(() => window.scrollTo(0, 1000));
  await shot("09b-causal-actions", 900);

  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
