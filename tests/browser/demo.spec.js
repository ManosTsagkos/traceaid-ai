const { test, expect } = require("@playwright/test");
const fs = require("node:fs/promises");

const staticUrl = "http://127.0.0.1:18767";
const liveUrl = "http://127.0.0.1:18768";

test("prepared demo loads without any API calls or browser errors", async ({ page }) => {
  const errors = [];
  const apiRequests = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => {
    if (new URL(request.url()).pathname.startsWith("/api/")) apiRequests.push(request.url());
  });
  await page.goto(staticUrl);
  await expect(page.locator(".example-card")).toHaveCount(6);
  await expect(page.locator(".status-label")).toHaveText("Prepared portfolio demo");
  await expect(page.locator(".live-label")).toHaveText("SAMPLE");
  await expect(page.locator("#request-url")).toBeDisabled();
  await expect(page.locator("#execute-probe")).toBeDisabled();
  await expect(page.locator("#use-ai")).toBeDisabled();
  await page.locator("#analyze-button").click();
  await expect(page.locator("#diagnosis-title")).toHaveText("Authentication was rejected");
  await expect(page.locator("#fallback-notice")).toContainText("Prepared demo");
  await expect(page.locator("#artifact-curl")).not.toContainText("demo-expired-token");
  expect(apiRequests).toEqual([]);
  expect(errors).toEqual([]);
});

const cases = [
  ["Expired bearer token", "Authentication was rejected", "GET"],
  ["Payload validation failure", "Payload validation failed", "POST"],
  ["Rate limit exceeded", "API rate limit exceeded", "GET"],
  ["Missing JSON content type", "Unsupported request media type", "POST"],
  ["Wrong HTTP method", "HTTP method is not allowed", "GET"],
  ["Upstream request timeout", "Request timed out", "GET"]
];

for (const [name, title, method] of cases) {
  test(`prepared case: ${name}`, async ({ page }) => {
    await page.goto(staticUrl);
    await page.getByRole("button", { name: `Load case: ${name}`, exact: true }).click();
    await expect(page.locator("#diagnosis-title")).toHaveText(title);
    await expect(page.locator("#artifact-curl")).toContainText(method);
    await page.getByRole("tab", { name: "Python", exact: true }).click();
    await expect(page.locator("#panel-python")).toBeVisible();
    await expect(page.locator("#artifact-python")).toContainText("import httpx");
    await page.getByRole("tab", { name: "pytest", exact: true }).click();
    await expect(page.locator("#artifact-pytest")).toContainText("test_corrected_api_request_regression");
    if (name === "Missing JSON content type") {
      await expect(page.locator("#artifact-curl")).toContainText("Content-Type: application/json");
    }
  });
}

test("copy, keyboard tabs, and JSON/Markdown exports preserve the real report", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.goto(staticUrl);
  await page.locator("#empty-demo-button").click();
  await expect(page.locator("#result-content")).toBeVisible();
  await page.locator("#tab-curl").focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.locator("#tab-python")).toBeFocused();
  await expect(page.locator("#tab-python")).toHaveAttribute("aria-selected", "true");
  await page.locator("#copy-code-button").click();
  await expect(page.locator("#copy-code-button span")).toHaveText("Copied");
  const code = await page.locator("#artifact-python").textContent();
  const clipboard = await page.evaluate(() => navigator.clipboard.readText());
  expect(clipboard.replace(/\r\n/g, "\n")).toBe(code);
  const jsonPromise = page.waitForEvent("download");
  await page.locator("#export-json").click();
  const json = JSON.parse(await fs.readFile(await (await jsonPromise).path(), "utf8"));
  expect(json.id).toBe("demo_expired-token");
  expect(json.mode).toBe("rules");
  expect(json.redacted_request.headers.Authorization).not.toContain("demo-expired-token");
  expect(json.artifacts.python_snippet).toBe(code);
  const markdownPromise = page.waitForEvent("download");
  await page.locator("#export-markdown").click();
  expect(await fs.readFile(await (await markdownPromise).path(), "utf8")).toBe(json.artifacts.markdown_report);
});

test("demo works under a GitHub Pages subpath", async ({ page }) => {
  await page.route("**/traceaid-ai/**", async route => {
    const asset = new URL(route.request().url()).pathname.replace("/traceaid-ai/", "");
    const response = await page.request.get(`${staticUrl}/${asset || "index.html"}`);
    await route.fulfill({ response });
  });
  await page.goto(`${staticUrl}/traceaid-ai/`);
  await expect(page.locator(".example-card")).toHaveCount(6);
  await page.locator("#hero-demo-button").click();
  await expect(page.locator("#result-content")).toBeVisible();
});

test("mobile prepared demo has no page overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(staticUrl);
  await page.getByRole("button", { name: "Load case: Wrong HTTP method", exact: true }).click();
  await expect(page.locator("#diagnosis-title")).toHaveText("HTTP method is not allowed");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("local app uses the actual API for custom evidence and exports redacted data", async ({ page }) => {
  await page.goto(liveUrl);
  await expect(page.locator(".example-card")).toHaveCount(6);
  await page.locator("#request-url").fill("https://api.example.com/v1/private");
  await page.locator("#request-headers").fill('{"Authorization":"Bearer browser-secret"}');
  await page.locator("#observed-details").evaluate(element => { element.open = true; });
  await page.locator("#status-code").fill("403");
  const responsePromise = page.waitForResponse(response => response.url().endsWith("/api/v1/diagnose"));
  await page.locator("#analyze-button").click();
  const response = await responsePromise;
  expect(response.ok()).toBe(true);
  expect(await response.text()).not.toContain("browser-secret");
  await expect(page.locator("#diagnosis-title")).toHaveText("Request is not permitted");
  await expect(page.locator("#fallback-notice")).toBeHidden();
  const downloadPromise = page.waitForEvent("download");
  await page.locator("#export-json").click();
  const downloaded = await fs.readFile(await (await downloadPromise).path(), "utf8");
  expect(downloaded).not.toContain("browser-secret");
  expect(JSON.parse(downloaded).diagnosis.category).toBe("authorization");
});

test("local API failure shows an error without manufacturing a diagnosis", async ({ page }) => {
  await page.goto(liveUrl);
  await expect(page.locator(".example-card")).toHaveCount(6);
  await page.locator("#load-demo-button").click();
  await page.route("**/api/v1/diagnose", route => route.abort());
  await page.locator("#analyze-button").click();
  await expect(page.locator("#error-state")).toBeVisible();
  await expect(page.locator("#result-content")).toBeHidden();
});

test("local invalid JSON is caught before submitting", async ({ page }) => {
  await page.goto(liveUrl);
  await expect(page.locator(".example-card")).toHaveCount(6);
  await page.locator("#load-demo-button").click();
  await page.locator("#request-headers").fill("{bad-json}");
  await page.locator("#analyze-button").click();
  await expect(page.locator("#request-headers")).toHaveAttribute("aria-invalid", "true");
  await expect(page.locator("#result-content")).toBeHidden();
});

test("API docs bootstrap and fetch OpenAPI under their real security policy", async ({ page }) => {
  // Keep CI offline while exercising the actual CDN allow-list and inline
  // nonce. Rendering internals of Swagger's third-party bundle are out of scope.
  await page.route("https://cdn.jsdelivr.net/**", async route => {
    if (route.request().url().endsWith(".css")) {
      await route.fulfill({ contentType: "text/css", body: "body { margin: 0; }" });
      return;
    }
    await route.fulfill({
      contentType: "application/javascript",
      body: `
        window.SwaggerUIBundle = function (options) {
          fetch(options.url).then(response => response.json()).then(schema => {
            const container = document.querySelector(options.dom_id);
            container.textContent = schema.info.title;
            container.dataset.paths = Object.keys(schema.paths).join(" ");
          });
          return {};
        };
        window.SwaggerUIBundle.presets = { apis: {} };
        window.SwaggerUIBundle.SwaggerUIStandalonePreset = {};
      `
    });
  });
  await page.route("https://fastapi.tiangolo.com/**", route => route.fulfill({ status: 204 }));
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto(`${liveUrl}/docs`);
  await expect(page.locator("#swagger-ui")).toHaveText("TraceAid AI");
  await expect(page.locator("#swagger-ui")).toHaveAttribute("data-paths", /\/api\/v1\/diagnose/);
  expect(errors).toEqual([]);
});
