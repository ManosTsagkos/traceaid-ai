const { chromium } = require("@playwright/test");
const { pathToFileURL } = require("node:url");
const path = require("node:path");

(async () => {
  const browser = await chromium.launch({ channel: process.env.TRACEAID_BROWSER_CHANNEL || undefined });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1050 }, reducedMotion: "reduce" });
    await page.goto(pathToFileURL(path.resolve("site/index.html")).href);
    await page.locator(".example-card").last().waitFor();
    await page.screenshot({ path: "docs/assets/traceaid-hero.png" });
    await page.locator("#analyze-button").click();
    await page.locator("#result-content").waitFor({ state: "visible" });
    await page.locator(".workbench-section").screenshot({
      path: "docs/assets/traceaid-workbench.png",
      style: ".site-header, .skip-link, .toast { visibility: hidden !important; }"
    });
    console.log("Updated prepared demo screenshots.");
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
